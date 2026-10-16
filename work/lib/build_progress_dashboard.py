# -*- coding: utf-8 -*-
"""生成「进度总览」网页：把散在 JSON 里的产出汇总成一张能打开的页面。

存在理由
    此前的产出（MCA、入口面检验、鼻窦标签、签字链路脚本）只存在于
    JSON 和终端输出里，复核页 index.html 上完全看不到。本脚本把它们
    汇总成一个自包含页面，并显式给出"下一步人该做什么"。

红线
    - 只读已有 JSON，不重算、不修改任何掩膜或候选点。
    - 缺失的项一律显示"未跑/缺失"，禁止用占位数字填充。
    - 不产患者流场数据。

用法
    python work/lib/build_progress_dashboard.py
    输出 work/进度总览.html
"""

from __future__ import annotations

import html
import json
import os
from datetime import datetime
from coarse_localization_summary import summarize_localization
# 2026-10-16 用户裁定「接回」：主进度页原本只汇总它自己认识的几个 JSON，
# **完全不读 tasks/**（因而 2026-10-15 时任务卡只到 T-010、且重跑也刷不新）。
# 现复用 build_progress_cards 的只读扫描器，把任务卡真值注入本页。
# 复用而非复制：两处共用同一套提取口径，避免两份实现静默分叉。
from build_progress_cards import scan_cards, summarize as summarize_cards

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.dirname(HERE)
CASES = ("p0", "p1", "p2", "p3", "p3t1")
CASE_LABEL = {
    "p0": "例0（浙一 / Philips 0.35mm 各向同性）",
    "p1": "患者1（深圳二院 / 联影 uCT760）",
    "p2": "患者2（复旦眼耳鼻喉科 / 西门子 Flash）",
    "p3": "患者3 t2（湘雅三院 / 联影 uCT968）",
    "p3t1": "患者3 t1（湘雅三院 / 联影 uCT710）",
}


def load(path):
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def e(v):
    return html.escape(str(v)) if v is not None else "—"


def num(v, nd=3, suffix=""):
    if v is None:
        return "—"
    return f"{v:.{nd}f}{suffix}"


def sci(v, nd=2):
    """小数量级（如 7.2e-07）用科学计数法，避免渲染成 0.000。"""
    if v is None:
        return "—"
    return f"{v:.{nd}e}"


M2_ZH = {
    "imposed_equal_split_baseline_0.5_0.5": "等分 0.5/0.5（施加）",
    "laminar": "层流",
    "direct_solver_call_outside_prescribed_wrapper": "带外直调 simpleFoam（不走 prescribed 封装器）",
}


def zh_or_raw(value, table=M2_ZH):
    return table.get(value, value)


def mesh_zh(raw):
    """M2 声明里的网格描述英译中；声明变更导致对不上时原样返回，不静默错译。"""
    if raw == ("b15 patient surface, Netgen maxh=1.0 repaired, 1161194 cells, "
               "585 det<0.001, 114 low-interpolation-weight faces, "
               "max non-orthogonality 87.3 deg"):
        return ("b15 患者表面，Netgen maxh=1.0 修复版，1,161,194 cells，"
                "585 个 det<0.001，114 个低插值权面，最大非正交 87.3°")
    return raw


def cell(v, cls=""):
    return f'<td class="{cls}">{v}</td>' if cls else f"<td>{v}</td>"


def load_feedback_audit():
    path = os.path.join(WORK, "06_auto_landmarks", "feedback_review", "audit.json")
    audit = load(path)
    if not isinstance(audit, dict):
        return {
            "status": "not_generated",
            "observations": 0,
            "matched": 0,
            "unresolved": 0,
            "source": path,
        }
    feedback = audit.get("feedback", [])
    if not isinstance(feedback, list):
        feedback = []
    matched = sum(bool(item.get("bound_to_current_proposal")) for item in feedback
                  if isinstance(item, dict))
    valid_identity = (audit.get("schema") == "landmark_feedback_audit/v1"
                      and audit.get("coordinate_system") == "LPS"
                      and audit.get("unit") == "mm")
    return {
        "status": "diagnostic_review_complete" if valid_identity else "invalid",
        "observations": len(feedback),
        "matched": matched,
        "unresolved": len(feedback) - matched,
        "source": path,
        "integrity": bool(audit.get("input_integrity_verified")),
    }


def load_phantom_validation():
    path = os.path.join(WORK, "07_cfd_pipeline", "solver_reference",
                        "phantom_validation", "validation.json")
    report = load(path)
    if not isinstance(report, dict) or report.get("schema") != "nasal_cfd_phantom_validation/v1":
        return {"status": "not_generated", "path": path}
    levels = report.get("levels", [])
    errors = [float(level.get("delta_p_rel_error")) for level in levels
              if isinstance(level, dict) and level.get("delta_p_rel_error") is not None]
    return {
        "status": report.get("verdict", "invalid") if isinstance(report.get("checks"), dict) else "invalid",
        "path": path,
        "checks": report.get("checks", {}),
        "errors": errors,
    }


def load_m2_declaration():
    """读患者网格工程实证的机器可读声明（M2 双轨收口，T-006 Run 1）。

    红线沿用本脚本总则：只读已有 JSON；clinical_status 恒显，禁止把
    工程实证渲染成患者分流结论。
    """
    path = os.path.join(os.path.dirname(WORK), "outputs", "M2收口", "m2_run_declaration.json")
    decl = load(path)
    if not isinstance(decl, dict) or decl.get("schema") != "nasal_cfd_m2_engineering_closure/v1":
        return {"status": "not_generated", "path": path}
    criteria = decl.get("primary_criteria", {})
    recorded = decl.get("recorded_items", {})
    return {
        "status": "closure_declared",
        "path": path,
        "clinical_status": decl.get("clinical_status"),
        "ruled_at": decl.get("ruled_at"),
        "closure_type": decl.get("closure_type"),
        "run": decl.get("run", {}),
        "condition": decl.get("operating_condition", {}),
        "criteria": criteria,
        "recorded": recorded,
    }


def m2_criteria_rows(m2):
    """四条主判据 + 一条记录项，逐条带实测值；数字全部来自声明 JSON。"""
    c = m2["criteria"]
    r = m2["recorded"]
    dp = c.get("delta_p_in_band_Pa", {})
    band = dp.get("band_Pa") or [None, None]
    mass = c.get("mass_imbalance_fraction_max", {})
    mon = c.get("monitor_relative_change", {})
    res = r.get("residual_convergence", {})
    stable = c.get("stable_no_crash", {}).get("evidence") or ""
    stable_zh = ("533 步无 FOAM FATAL / sigFPE，越过 T-004 崩溃点（T=260）273 步"
                 if stable.startswith("533 steps") else e(stable))
    rows = [
        ("稳定不崩（越过 T-004 崩溃点）", "—", stable_zh,
         bool(c.get("stable_no_crash", {}).get("met"))),
        ("Δp 入带（贴下限）",
         f'{num(band[0], 0)}–{num(band[1], 0)} Pa',
         num(dp.get("value_Pa"), 2, " Pa"),
         bool(dp.get("met"))),
        ("质量不平衡（稳态段）", num(mass.get("screen"), 3),
         sci(mass.get("value")), bool(mass.get("met"))),
        ("监测量稳定（Δp 窗间相对变化）", num(mon.get("screen") * 100, 2, "%"),
         num(mon.get("value") * 100, 4, "%"), bool(mon.get("met"))),
        ("残差收敛（记录项）", sci(res.get("screen_target_residual_max")),
         sci(res.get("residual_max_Ux")) + "（Ux 终值）",
         bool(res.get("achieved"))),
    ]
    out = []
    for name, screen, value, met in rows:
        verdict = ('<span class="ok">过</span>' if met
                   else '<span class="warn">未达（记录项）</span>')
        out.append("<tr>" + cell(e(name)) + cell(e(screen))
                   + cell(value) + cell(verdict) + "</tr>")
    return "".join(out)


def build_rows():
    rows = []
    for c in CASES:
        lm = load(os.path.join(WORK, "06_auto_landmarks", c, "landmarks.json")) or {}
        lms = lm.get("landmarks", {})
        n_points = len(lms)
        n_review = sum(
            1 for v in lms.values() if isinstance(v, dict) and v.get("status") == "needs_review"
        )

        mca = load(os.path.join(WORK, "05_ts_seg", c, "anatomy", "mca_%s.json" % c)) or {}
        ps = mca.get("per_side", {}) if isinstance(mca, dict) else {}
        left = ps.get("left", {})
        right = ps.get("right", {})

        ep = load(os.path.join(WORK, "06_auto_landmarks", c, "entry_plane_check_%s.json" % c)) or {}
        eps = ep.get("per_side", {}) if isinstance(ep, dict) else {}

        sin = load(os.path.join(WORK, "05_ts_seg", c, "anatomy", "sinus_%s.json" % c))

        rows.append(
            {
                "case": c,
                "label": CASE_LABEL.get(c, c),
                "n_points": n_points,
                "n_review": n_review,
                "localization": summarize_localization(lm),
                "mca_l": left.get("primary_mca_cm2"),
                "mca_r": right.get("primary_mca_cm2"),
                "ratio_l": left.get("ratio_to_asian_reference"),
                "ratio_r": right.get("ratio_to_asian_reference"),
                "artifact": bool(
                    left.get("entry_boundary_artifact_suspected")
                    or right.get("entry_boundary_artifact_suspected")
                ),
                "disc": int(left.get("discontinuity_slabs", 0) or 0)
                + int(right.get("discontinuity_slabs", 0) or 0),
                "entry_verdict": (
                    eps.get("left", {}).get("verdict_zh") if isinstance(eps, dict) else None
                ),
                "entry_schema": ep.get("schema"),
                "entry_sides": eps if isinstance(eps, dict) else {},
                "sinus": sin,
            }
        )
    return rows


def sinus_cell(sin):
    if not sin:
        return cell('<span class="muted">未跑</span>')
    sm = sin.get("sinuses", {}).get("sinus_maxillary", {})
    sf = sin.get("sinuses", {}).get("sinus_frontal", {})
    parts = []
    for tag, s in (("上颌窦", sm), ("额窦", sf)):
        st = s.get("ostium_status")
        cls = {
            "candidate_open_position_unverified": "warn",
            "subvoxel_unknown": "muted",
        }.get(st, "muted")
        zh = {
            "candidate_open_position_unverified": "候选开放·位置待确认",
            "subvoxel_unknown": "亚体素·不可判定",
            "closed_in_ct_air_domain": "空气域不连通",
        }.get(st, st or "—")
        w = s.get("channel_width_mm_estimate")
        parts.append(
            f'{tag} {num(s.get("volume_ml"), 2)} mL · '
            f'<span class="{cls}">{e(zh)}</span>'
            + (f' · 宽≈{num(w, 2)} mm' if w else "")
        )
    return cell("<br>".join(parts))


def render(rows, feedback=None):
    feedback = feedback or load_feedback_audit()
    m2 = load_m2_declaration()
    phantom = load_phantom_validation()
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    entry_sides = [s for r in rows if r.get("entry_schema") == "entry_plane_check/v2"
                   for s in r.get("entry_sides", {}).values()]
    if entry_sides:
        entry_no_hit = sum(s.get("verdict") == "no_tissue_hit_in_observed_ray" for s in entry_sides)
        entry_hit = sum(s.get("verdict") == "tissue_hit_in_observed_ray" for s in entry_sides)
        entry_truncated = sum(bool(s.get("fov_truncated")) for s in entry_sides)
        entry_summary = (f"v2 已记录 {len(entry_sides)} 侧：观测范围内未命中 HU>-200 为 {entry_no_hit} 侧，"
                         f"命中为 {entry_hit} 侧，采样范围截断为 {entry_truncated} 侧。")
    else:
        entry_summary = "v2 采样记录尚未生成。"
    if feedback["status"] == "diagnostic_review_complete":
        feedback_title = "诊断核对已完成"
        feedback_text = (f'已读取 {feedback["observations"]} 条人工意见，其中 '
                         f'{feedback["matched"]} 条可绑定当前候选，'
                         f'{feedback["unresolved"]} 条仍需解释或人工复核。'
                         '这一步不改变候选坐标，也不代表临床接受。')
        feedback_class = "done"
    elif feedback["status"] == "not_generated":
        feedback_title = "诊断核对未生成"
        feedback_text = "未找到人工意见审计摘要；工作台继续保持患者 CFD 门禁锁定。"
        feedback_class = "todo"
    else:
        feedback_title = "诊断核对文件无效"
        feedback_text = "审计摘要身份不符合预期，不能用于绑定候选或解锁患者计算。"
        feedback_class = "block"
    if phantom["status"] == "pass":
        phantom_title = "通过"
        phantom_text = "圆管非患者闭环满足预设压降、收敛、守恒和峰值速度检查。"
        phantom_class = "done"
    elif phantom["status"] == "fail":
        phantom_title = "未通过严格压降标准"
        coarse, fine = (phantom.get("errors") + [None, None])[:2]
        phantom_text = ("求解链路已跑完；质量守恒、收敛和峰值速度检查通过，"
                        f"但粗/细网格压降相对误差为 {num(coarse * 100, 1) if coarse is not None else '—'}% / "
                        f"{num(fine * 100, 1) if fine is not None else '—'}%。"
                        "误差原因需要独立对照检验，不能据此放行患者计算。")
        phantom_class = "block"
    else:
        phantom_title = "未生成"
        phantom_text = "未找到非患者圆管闭环验证报告。"
        phantom_class = "todo"
    trs = []
    for r in rows:
        art = '<span class="warn">入口边界疑似伪影</span>' if r["artifact"] else "—"
        trs.append(
            "<tr>"
            + cell(f'<b>{e(r["case"])}</b><br><span class="muted small">{e(r["label"])}</span>')
            + cell(f'{r["n_points"]} 点<br><span class="muted small">'
                   + (f'{r["n_review"]} 点 needs_review' if r["n_review"] else "全部 proposed")
                   + "</span>")
            + cell(num(r["mca_l"], 3) + " / " + num(r["mca_r"], 3))
            + cell(f'×{num(r["ratio_l"], 2)} / ×{num(r["ratio_r"], 2)}')
            + cell(art)
            + sinus_cell(r["sinus"])
            + "</tr>"
        )

    coarse_rows = []
    coarse_states = {'search_prior': '可用于搜索与对照', 'display_only': '预计点仅供显示',
                     'unavailable': '粗定位不适用，使用本例 CT', 'not_generated': '未生成粗定位记录'}
    for r in rows:
        summary = r.get('localization') or summarize_localization({})
        details = (f"搜索/对照 {summary['search_prior_points']} 点；仅显示 {summary['display_only_points']} 点；"
                   f"局部搜索 {len(summary['local_search_landmarks'])} 点；回退 {len(summary['fallback_landmarks'])} 点")
        if summary['outside_search_box_landmarks']:
            details += f"；{len(summary['outside_search_box_landmarks'])} 点超框待复核"
        if summary['status'] == 'unavailable' and summary['palate_rms_mm'] is not None:
            details += f"；硬腭拟合残差 {num(summary['palate_rms_mm'], 3)} mm"
        refs = ', '.join(summary['reference_cases']) or '无适用参考'
        warning = ', '.join(w['case'] for w in summary['reference_quality_warnings'])
        if warning:
            refs += '；带质量警告的粗定位参考：' + warning
        coarse_rows.append('<tr>' + cell(e(r['case']))
                           + cell(e(coarse_states[summary['status']]) + '<br><span class="small muted">' + e(details) + '</span>')
                           + cell(e(refs) + f"<br>{summary['independent_reference_patients']} 位独立患者")
                           + cell(num(summary['max_refinement_delta_mm'], 2, ' mm')
                                  + f"<br><span class=\"small muted\">{summary['compared_points']} 点可比较</span>")
                           + cell(f'<a href="/landmark-review/{e(r["case"])}/coarse_adjustment.json">坐标与搜索框</a>') + '</tr>')
    if m2["status"] == "closure_declared":
        crit = m2["criteria"]
        m2_all_met = all(isinstance(v, dict) and v.get("met") for v in crit.values())
        m2_class = "done" if m2_all_met else "block"
        m2_title = "四条主判据全部满足" if m2_all_met else "存在未满足主判据"
        cond = m2["condition"]
        run = m2["run"]
        m2_card = f"""
<div class="card {m2_class}">
<h2>③b 患者网格工程实证（T-006 Run 1，M2 双轨收口）：{m2_title}</h2>
<p><span class="tag">链路验证</span>网格：{e(mesh_zh(cond.get("mesh")))}。工况：{num(cond.get("total_inspiratory_flow_lpm"), 0)} L/min {e(zh_or_raw(cond.get("flow_split")))} ＋ 鼻咽出口 {num((cond.get("nasopharynx_outlet") or {}).get("value_Pa"), 0)} Pa（gauge 静压，非 Δp）＋ {e(zh_or_raw(cond.get("turbulence_model")))}。执行方式：{e(zh_or_raw(run.get("execution_mode")))}，人工终止于 T=533（残差触底后缓升，核心判据已可判）。</p>
<div class="table-scroll"><table>
<tr><th>判据</th><th>屏值</th><th>Run 1 实测</th><th>判定</th></tr>
{m2_criteria_rows(m2)}
</table></div>
<div class="small muted" style="margin-top:8px">
残差收敛未达 → <code>numerical_validation: {e(m2["recorded"].get("numerical_validation"))}</code>（契约合法声明，不宣称收敛）；
平台期候选成因 H1–H4 与 Δp 贴带下限的灵敏度，留给 M3 36 格矩阵判别。
</div>
<p class="small" style="margin-top:8px"><b>恒带标注</b>：<code>clinical_status: {e(m2["clinical_status"])}</code>——
链路验证证据，<b>不得报告为患者分流结论</b>；契约有效患者 <code>cfd_result</code> 仍为 0（医学门 + solver adapter 未就绪）。<br>
来源：<code>outputs/M2收口/m2_run_declaration.json</code>（用户 {e(m2["ruled_at"])} 裁定双轨收口）；
过程说明 <code>outputs/M2收口/M2收口说明.md</code>；判据重议 <code>plan/M2出口判据重议.md</code>。</p>
</div>
"""
    else:
        m2_card = """
<div class="card todo">
<h2>③b 患者网格工程实证：未生成</h2>
<p>未找到患者网格工程实证的机器可读声明；工作台不渲染任何患者试算数字。</p>
</div>
"""
    # ---- ⑥b 任务卡进度（2026-10-16 接回）----
    # 只读扫描 tasks/ + MEMORY.md；不判定、不归一化、不用占位状态填充。
    _cards = scan_cards()
    _cst = summarize_cards(_cards)
    _rows = []
    for c in _cards:
        src = "验收" if c["acc_line"] else ("记忆" if c["mem_status"] != "—" else "卡头")
        flag = ' <span class="tag">可疑</span>' if c["suspicious"] else ""
        cls = {"VERIFIED": "ok", "CLOSED": "ok", "DONE": "ok",
               "PARTIAL": "warn", "PAUSED": "warn",
               "BLOCKED": "bad", "已废弃": "bad", "打回": "bad"}.get(c["shown"], "muted")
        rowstyle = ' style="background:#e4e4e4"' if not c["agree"] else ""
        _rows.append(
            f'<tr{rowstyle}><td><b>{e(c["id"])}</b></td>'
            f'<td>{e(c["title"])[:76]}</td>'
            f'<td class="{cls}">{e(c["shown"])}{flag}</td>'
            f'<td class="muted small">{e(src)}</td>'
            f'<td class="small">{(e(c["acc_line"])[:120] if c["acc_line"] else "—")}</td></tr>'
        )
    cards_card = f"""<div class="card" id="task-cards">
<h2>⑥b 任务卡进度</h2>
<p class="small">共 <b>{_cst['n']}</b> 张卡 ｜ {_cst['summary']} ｜
三列不一致 <b>{_cst['n_disagree']}</b> 张（红底）｜
含否定语义标可疑 <b>{_cst['n_susp']}</b> 张</p>
<div class="table-scroll"><table>
<tr><th>卡</th><th>标题</th><th>采用状态</th><th>来源</th><th>验收记录（原文）</th></tr>
{''.join(_rows)}
</table></div>
<p class="small muted" style="margin-top:8px">
<b>怎么读：</b>状态词<b>照抄原文、不归一化</b>——<code>DONE</code> 是多张卡卡头自用的
「结项」写法，<code>BLOCKED</code> 是项目记忆里的描述性标记（AGENTS.md 规定阻塞时状态
回退 <code>OPEN</code>、原因记验收记录，两者可并存）。采用优先级
<b>验收记录 &gt; 项目记忆 &gt; 卡头</b>：卡头实测大面积缺失且滞后（T-036 卡头
<code>EXECUTING</code> 而验收已是 <code>VERIFIED</code>），故只作兜底。<br>
完整三列对照（卡头 / 验收 / 记忆）见
<a href="/workspace/progress-cards.html">任务卡进度独立页</a>。
本表由 <code>work/lib/build_progress_cards.py</code> 只读扫描生成，
<b>不声称等于人工真值</b>；真值以 <code>state/状态.md</code> 与
<code>.workbuddy/memory/MEMORY.md</code> 为准。
</p>
</div>"""

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>鼻腔 CFD 项目 · 进度总览</title>
<style>
/* 令牌与 workspace/pro/tokens.css 同值（单一真源）；chrome 单色，
   状态靠明度 + 字重 + 字形区分，不靠色相。圆角 2–3px 属新版语言。 */
:root{{--bg:#ebebeb;--card:#ffffff;--ink:#1a1a1a;--line:#dcdcdc;--line2:#c8c8c8;
--mut:#6e6e6e;--faint:#9a9a9a;--soft:#f0f0f0;--soft2:#e4e4e4;--accent:#1a1a1a;
--warn:#3d3d3d;--warn-bg:#efefef;--bad:#000000;--bad-bg:#e2e2e2;
--mono:ui-monospace,Consolas,"Cascadia Mono",monospace;color-scheme:light}}
*{{box-sizing:border-box}}
body{{overflow-wrap:anywhere}}
body{{margin:0;padding:24px;background:var(--bg);color:var(--ink);
font:14px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;}}
.wrap{{max-width:1180px;margin:0 auto}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:22px 0 10px}}
.sub{{color:var(--mut);font-size:13px;margin-bottom:18px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:3px;
padding:16px 18px;margin-bottom:14px}}
.todo{{border-left:3px solid var(--line2)}}
.block{{border-left:3px solid var(--bad)}}
.done{{border-left:3px solid var(--soft2)}}
ol{{margin:8px 0 0 20px;padding:0}} li{{margin:6px 0}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
.table-scroll{{max-width:100%;overflow-x:auto}}
th,td{{border:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}}
th{{background:var(--soft);font-weight:600}}
tr:nth-child(even) td{{background:#fbfbfb}}
.ok{{color:var(--ink);font-weight:700}}
.warn{{color:var(--mut);font-weight:700;font-style:italic}}
.bad{{color:var(--bad);font-weight:700;text-decoration:underline}}
.muted{{color:var(--mut)}} .small{{font-size:12px}}
code{{background:var(--soft);padding:1px 5px;border-radius:2px;font-size:12.5px;
font-family:var(--mono)}}
a{{color:var(--accent);text-decoration:underline}}
.tag{{display:inline-block;background:var(--soft2);color:var(--ink);border:1px solid var(--line2);
border-radius:2px;padding:1px 7px;font-size:12px;margin-right:6px}}
</style><script src="/workspace/embed.js" defer></script></head><body><div class="wrap">

<h1>鼻腔 CFD 空气域复核 · 进度总览</h1>
<div class="sub">生成时间 {e(now)} ｜ 只读汇总，不修改任何掩膜与候选点 ｜
缺失项一律标「未跑」，无占位数字</div>

<div class="card" style="border-left:3px solid var(--accent)">
<h2>项目主线已确定</h2>
<p>本项目按“匿名 CT → 自动分割 → UAS 粗定位 → 本例 CT 精标定 → 可视人工检验 → 版本化几何 → CFD → 实际结果”推进。阶段一只做患者原始鼻腔建模和气流分析；结构修改、二次模拟和鼻塞设计留到后续阶段。</p>
<p class="small" style="margin-top:8px">主线版本：2026-10-14 ｜ 当前里程碑：<b>M3 验证矩阵与交付</b>。
M1（体网格）与 M2（患者求解）已于 2026-10-14 按用户裁定的双轨收口；
两道前置门已裁定：医学复核门选 B（先跑矩阵，产物恒标
<code>generalisation_test_only_no_human_review</code>），solver adapter 门选 A（派卡 T-009 实现）。
<b>下一项（2026-10-15 现状）</b>：T-009 / T-010 已结项；M3 患者几何轴 36 格仍卡在
T-011 Phase A 例0 的 N6 开孔裁剪门（<code>clip_failed</code>，输入未通过入口验收，
未放行、不硬闯）；纯数值轴已由 T-036 / T-037 用合成圆管走完 H1–H4 判别。
逐卡状态见下方「⑥b 任务卡进度」。</p>
</div>

<div class="card" id="coarse-localization">
<h2>粗标定已接入：统一坐标预设 → 本例影像精调</h2>
<p>以硬腭及鼻腔方向校正姿态，在 UAS（患者左、后、上）中按鼻腔三轴范围转移参考标点。粗定位预设搜索范围，本例 CT 确定候选与平面。CT 和气道模型保留真实毫米尺寸。</p>
<div class="table-scroll"><table>
<tr><th>病例</th><th>本例适用性与实际搜索</th><th>本例参考来源</th><th>最大粗→精偏移</th><th>证据</th></tr>
{''.join(coarse_rows)}
</table></div>
<p class="small muted" style="margin-top:8px">参考库逐例排除本人、相同 CT 和同病例；p3 / p3t1 按同一患者等权。局部失败回退本例解剖范围搜索。偏移是粗点到自动候选的距离，医学准确性仍待独立人工真值验证。</p>
<p class="small" style="margin-top:8px">粗定位参考接受与正式解剖确认分别记录。下一步：在<a href="/landmark-review/index.html">切片复核</a>检查精调点、超框提示和入口/出口平面，再生成正式审核记录。</p>
</div>

<div class="card todo">
<h2>① 当前人工确认入口</h2>
<ol>
<li><a href="/landmark-review/index.html">标定审核</a>：五组扫描，共 25 个候选点，尚待正式解剖确认。</li>
<li><a href="/landmark-review/feedback_review/index.html">意见核对</a>：点位与平面方向需要结合本例 CT 分别复核，跨病例绝对 XYZ 不能作为统一位置标准。</li>
<li>审核记录与原候选分开保存；接受、拒绝或调整记录均不会直接修改分割或解锁患者计算。</li>
</ol>
<div class="small muted" style="margin-top:8px">
正式审核记录仍需通过来源校验，并结合口腔、鼻窦与进出口边界确认。
</div>
</div>

<div class="card {feedback_class}">
<h2>② 人工意见诊断核对：{feedback_title}</h2>
<p>{e(feedback_text)}</p>
<p class="small muted" style="margin-top:8px">来源：<code>06_auto_landmarks/feedback_review/audit.json</code> ｜
页面：<a href="/landmark-review/feedback_review/index.html">人工意见与局部切面对照</a></p>
</div>

<div class="card {phantom_class}">
<h2>③ 非患者求解闭环：{phantom_title}</h2>
<p>{e(phantom_text)}</p>
<p class="small muted" style="margin-top:8px">报告：<a href="/solver_reference/phantom_validation/validation.json"><code>solver_reference/phantom_validation/validation.json</code></a> ｜ 仅用于工程链路验收，不含患者结果</p>
</div>

{m2_card}

<div class="card block">
<h2>④ 医学复核进度与仍锁住的 gate</h2>
<p>点位复核已完成：复核人王湧瑞 2026-10-07 对五例 ×5 点位给出 <b>25/25 accept</b>（记录于
<code>state/状态.md</code> R11 与 <code>plan/主计划.md</code> M3-S1 节）。
但点位正确 ≠ 契约门禁解锁——以下三项独立 gate 五例全 pending：</p>
<ul>
<li><b>口腔排除确认</b> —— 口咽/软腭那道屏障是否真的把口腔隔开了</li>
<li><b>鼻窦边界策略确认</b> —— G_sinus 里鼻窦按什么口径保留</li>
<li><b>最终几何确认</b> —— 进出口与壁面几何是否按复核版本定稿</li>
</ul>
<div class="small muted">
三项 gate 脚本默认 false，只有复核人确认后才置 true。用户 2026-10-14 裁定（R11 选 B）：
先跑 M3 矩阵做工程验证，产物恒标 <code>generalisation_test_only_no_human_review</code>，
契约有效患者 <code>cfd_result</code> 保持 0 直到三项 gate 关闭。
</div>
</div>

<div class="card">
<h2>⑤ 逐例状态</h2>
<div class="table-scroll"><table>
<tr><th>病例</th><th>自动定位</th><th>MCA 左/右 (cm²)</th><th>vs 亚洲参考 0.75</th>
<th>入口边界</th><th>鼻窦（craniofacial_structures）</th></tr>
{''.join(trs)}
</table></div>
<div class="small muted" style="margin-top:8px">
MCA = 最小截面积，跳过入口 3 mm 后测得；亚洲成人声反射参考 0.75 cm²，
<b>只当量级哨兵，不是合格线</b>。鼻窦一栏只有例0跑过（其余 4 例未跑 craniofacial_structures）。
</div>
</div>

<div class="card done">
<h2>⑥ 近期已完成</h2>
<ul>
<li><b>MCA 测量</b> <code>work/lib/measure_mca.py</code> —— 5 例全跑通，
10/10 侧落在参考值 0.94–1.81 倍。这是项目第一次有数字能跟外部文献对账</li>
<li><b>入口面检验</b> <code>work/lib/inspect_entry_plane.py</code> ——
{e(entry_summary)} 越出 CT 可采样范围的值保留为缺失，不延用边缘体素。
射线记录<b>不能确认入口位置、入口深度或鼻前庭缺失</b>；
没有命中阈值也不等于已识别鼻孔边缘，仍需三切面及局部结构复核。</li>
<li><b>鼻窦标签</b> <code>work/lib/measure_sinus_ostia.py</code> ——
例0 上颌窦 36.45 mL、额窦 3.14 mL，HU&gt;0 仅 1.54%/0.94%（鼻腔标签是 8.70%，
说明鼻窦标签基本就是空气域）。窦口用<b>逐级腐蚀测瓶颈</b>：
上颌窦通到 k=1（宽约 0.7–1.05 mm，候选开放），额窦仅 k=0（亚体素，不可判定）</li>
<li><b>签字链路最后一公里</b> <code>work/lib/confirm_landmark_review.py</code> ——
网页导出的决定 → 求解管线确认件，含哈希校验与门禁剩余项清单</li>
<li><b>医学点位复核 25/25 accept</b>（2026-10-07，王湧瑞）——
五例 ×5 点位全部接受；三项解剖 gate 仍 pending（见 ④）</li>
<li><b>M1 体网格双轨收口</b>（2026-10-14 用户裁定）——
患者 b15 网格已建成（maxh=1.0 修复版 1,161,194 cells）；出口主判据改为
「求解不崩 + Δp 入 10–100 Pa 带 + 质量不平衡 ≤1e-4」，<code>Mesh OK</code> 降为记录项，
<b>对外不得宣称 Mesh OK</b></li>
<li><b>T-004 / T-006 患者网格求解实证</b>（2026-10-14）——
同一网格唯一变量为数值设置：全项目模板（nNonOrthCorr 0 + p 无松弛）在 T=260
<code>sigFPE</code> 崩（T-004，其「网格致命」判定受混淆变量污染）；
改标定后 T-006 Run 1 <b>533 步无崩</b>、Δp <b>10.29 Pa 入带</b>（贴下限）、
质量不平衡 7.2e-7、监测量窗间变化 0.0079%（见 ③b）</li>
<li><b>M2 双轨收口 + T-008 契约口径</b>（2026-10-14）——
用户裁定 A：四条主判据过、residualControl 收敛降记录项
（<code>numerical_validation: unchecked</code>）；T-008 给契约补了两个诊断量取值口径，
四个屏值逐位未动，39 项测试全过（commit <code>0674fb7</code>）</li>
<li><b>换届接手与 WIP 处置</b>（2026-10-14 深夜，M3-S1）——
推翻黑板旧记录（「并行会话 5 个改动文件」实为 10-11/12 无任务卡遗留）；
4 个 commit 归档 WIP（网格缓存特性、CPU 亲和、连通性选择器、DICOM 扩展名）；
按 G6 保护性例外快照入库 90 个未跟踪文件；<code>.gitignore</code> 补医疗数据目录漏洞。
结论卡：<code>knowledge/20261014-nasal-cfd-M3-S1接手与WIP处置.md</code></li>
</ul>
</div>

{cards_card}

<div class="card">
<h2>⑦ 还差什么</h2>
<div class="table-scroll"><table>
<tr><th>项</th><th>状态</th><th>卡在谁</th></tr>
<tr><td>5 点人工复核</td><td class="ok">已 25/25 accept（2026-10-07，王湧瑞）</td><td>—</td></tr>
<tr><td>口腔排除 / 鼻窦策略 / 最终几何（三项 gate）</td><td class="bad">五例全 pending（R11；已裁定先跑矩阵不阻塞工程验证）</td><td>复核人／你</td></tr>
<tr><td>solver adapter 实现</td><td class="ok">T-009 <b>已结项</b>（2026-10-15，卡头 DONE）</td><td>—</td></tr>
<tr><td>网格缓存 WIP 转正</td><td class="ok">T-010 <b>已结项</b>（2026-10-15）：网格缓存 verdict 可依赖</td><td>—</td></tr>
<tr><td>M3 36 格验证矩阵（3 阈值 × 2 几何 × 3 网格 × 2 求解）</td><td class="warn">未跑；Phase A 例0 先行，CPU 独占车道以天计</td><td>我</td></tr>
<tr><td>K2 量化对照报告</td><td class="bad">外部阻塞：需求方阈值裁定 + 人工金标准</td><td>需求方</td></tr>
<tr><td>筛窦 / 蝶窦标签</td><td class="bad">TS 41 个 task 全无</td><td>人工标注</td></tr>
<tr><td>窦口通道位置确认</td><td class="bad">未验证（可能绕经筛窦）</td><td>人工看图</td></tr>
<tr><td>其余 4 例鼻窦推理</td><td class="warn">未跑</td><td>我（每例约 7 分钟）</td></tr>
<tr><td>真实表面 → 体网格 → 试算</td><td class="warn">工程链已通（b15 网格 + T-006 实证，见 ③b）；契约有效结果仍为 0</td><td>三项 gate + adapter</td></tr>
<tr><td>网页三 layer（流速/压力/湍流）</td><td class="warn">参考算例已支持，患者待契约解锁</td><td>医学门 / adapter</td></tr>
</table></div>
<div class="small muted" style="margin-top:8px">
状态口径：契约有效患者 <code>cfd_result</code> = 0（医学门 + <code>solver_adapter</code> 未就绪）；
③b 的工程实证数字恒带 <code>generalisation_test_only_no_human_review</code>，不计入患者结果。
</div>
</div>

<div class="card">
<h2>⑧ 文件清单</h2>
<div class="small">
复核页 <code>work/06_auto_landmarks/index.html</code> ｜
复核说明 <code>work/06_auto_landmarks/复核页使用说明.md</code><br>
MCA 汇总 <code>work/05_ts_seg/MCA测量汇总.md</code> ｜
鼻窦实测 <code>work/05_ts_seg/鼻窦标签与窦口连通性实测.md</code><br>
E 段脚本规格 <code>work/脚本编写方案-E段自动化.md</code> ｜
方案陈述 <code>work/方案陈述-鼻腔CFD空气域复核.md</code><br>
M2 收口 <code>outputs/M2收口/M2收口说明.md</code> ＋ <code>m2_run_declaration.json</code> ｜
判据重议 <code>plan/M2出口判据重议.md</code><br>
协作黑板 <code>plan/主计划.md</code>（M3-S1 排期）＋ <code>state/状态.md</code>（R11/R12 已裁定）｜
契约 <code>work/lib/cfd_contract.py</code><br>
结论卡 <code>knowledge/20261014-nasal-cfd-M3-S1接手与WIP处置.md</code>
</div>
</div>

</div></body></html>
"""
    return html_doc


def main():
    rows = build_rows()
    out = os.path.join(WORK, "进度总览.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render(rows, load_feedback_audit()))
    print("写出", out)
    for r in rows:
        print(
            f"  {r['case']}: MCA {num(r['mca_l'],3)}/{num(r['mca_r'],3)} cm2  "
            f"入口伪影={'是' if r['artifact'] else '否'}  "
            f"鼻窦={'已跑' if r['sinus'] else '未跑'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
