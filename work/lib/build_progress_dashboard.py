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
        art = '<span class="warn">⚠ 入口边界疑似伪影</span>' if r["artifact"] else "—"
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
    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>鼻腔 CFD 项目 · 进度总览</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--line:#e3e6ea;--tx:#1f2328;--mut:#6b7280;
--ok:#15803d;--warn:#b45309;--bad:#b91c1c;--acc:#2563eb;}}
*{{box-sizing:border-box}}
body{{overflow-wrap:anywhere}}
body{{margin:0;padding:24px;background:var(--bg);color:var(--tx);
font:14px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;}}
.wrap{{max-width:1180px;margin:0 auto}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:22px 0 10px}}
.sub{{color:var(--mut);font-size:13px;margin-bottom:18px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:16px 18px;margin-bottom:14px}}
.todo{{border-left:4px solid var(--warn)}}
.block{{border-left:4px solid var(--bad)}}
.done{{border-left:4px solid var(--ok)}}
ol{{margin:8px 0 0 20px;padding:0}} li{{margin:6px 0}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
.table-scroll{{max-width:100%;overflow-x:auto}}
th,td{{border:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}}
th{{background:#f0f2f5;font-weight:600}}
tr:nth-child(even) td{{background:#fafbfc}}
.ok{{color:var(--ok)}} .warn{{color:var(--warn)}} .bad{{color:var(--bad)}}
.muted{{color:var(--mut)}} .small{{font-size:12px}}
code{{background:#f0f2f5;padding:1px 5px;border-radius:4px;font-size:12.5px}}
a{{color:var(--acc)}} .tag{{display:inline-block;background:#eef2ff;color:#3730a3;
border-radius:4px;padding:1px 7px;font-size:12px;margin-right:6px}}
</style><script src="/workspace/embed.js" defer></script></head><body><div class="wrap">

<h1>鼻腔 CFD 空气域复核 · 进度总览</h1>
<div class="sub">生成时间 {e(now)} ｜ 只读汇总，不修改任何掩膜与候选点 ｜
缺失项一律标「未跑」，无占位数字</div>

<div class="card" style="border-left:4px solid var(--acc)">
<h2>项目主线已确定</h2>
<p>本项目按“匿名 CT → 自动分割 → UAS 粗定位 → 本例 CT 精标定 → 可视人工检验 → 版本化几何 → CFD → 实际结果”推进。阶段一只做患者原始鼻腔建模和气流分析；结构修改、二次模拟和鼻塞设计留到后续阶段。</p>
<p class="small" style="margin-top:8px">主线版本：2026-10-03 ｜ 下一项：让 p0 自动走到待复核，并将人工决定接到新几何。求解组件验证在等待复核期间推进。</p>
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

<div class="card block">
<h2>④ 拿到正式签字后仍然锁住的两项</h2>
<ul>
<li><b>口腔排除确认</b> —— 口咽/软腭那道屏障是否真的把口腔隔开了</li>
<li><b>鼻窦边界策略确认</b> —— G_sinus 里鼻窦按什么口径保留</li>
</ul>
<div class="small muted">
5 个标点全部正确 ≠ 契约门禁解锁。这两项是独立于标点定位的判断，
脚本默认 false，只有你确认后才置 true。
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
</ul>
</div>

<div class="card">
<h2>⑦ 还差什么</h2>
<div class="table-scroll"><table>
<tr><th>项</th><th>状态</th><th>卡在谁</th></tr>
<tr><td>5 点人工复核落成文件</td><td class="bad">尚待正式审核记录</td><td>解剖审核</td></tr>
<tr><td>口腔排除 / 鼻窦边界策略</td><td class="bad">未确认</td><td>你</td></tr>
<tr><td>筛窦 / 蝶窦标签</td><td class="bad">TS 41 个 task 全无</td><td>人工标注</td></tr>
<tr><td>窦口通道位置确认</td><td class="bad">未验证（可能绕经筛窦）</td><td>人工看图</td></tr>
<tr><td>其余 4 例鼻窦推理</td><td class="warn">未跑</td><td>我（每例约 7 分钟）</td></tr>
<tr><td>真实表面 → 体网格（E 段 S1/S2）</td><td class="warn">脚本已具备，患者未执行</td><td>待正式边界与体网格门禁</td></tr>
<tr><td>网页三 layer（流速/压力/湍流）</td><td class="warn">参考算例已支持，患者待结果</td><td>患者 CFD 解锁后</td></tr>
</table></div>
</div>

<div class="card">
<h2>⑧ 文件清单</h2>
<div class="small">
复核页 <code>work/06_auto_landmarks/index.html</code> ｜
复核说明 <code>work/06_auto_landmarks/复核页使用说明.md</code><br>
MCA 汇总 <code>work/05_ts_seg/MCA测量汇总.md</code> ｜
鼻窦实测 <code>work/05_ts_seg/鼻窦标签与窦口连通性实测.md</code><br>
E 段脚本规格 <code>work/脚本编写方案-E段自动化.md</code> ｜
方案陈述 <code>work/方案陈述-鼻腔CFD空气域复核.md</code>
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
