# -*- coding: utf-8 -*-
"""生成「任务卡进度」网页：把 tasks/*.md 的卡状态集中成一页，供工作台查看。

存在理由
    work/进度总览.html（build_progress_dashboard.py 产物）**不读 tasks/**，
    且卡头 `**状态**` 字段大面积缺失或滞后（2026-10-15 实测：38 张卡仅 6 张
    有卡头状态；T-036 卡头 EXECUTING 而验收记录已是 VERIFIED）。本脚本把
    三个来源并列展示，让滞后与矛盾**自己暴露出来**，而不是假装自动判定准确。

红线（沿用本脚本总则，对应项目已 7 次「判据合法但与事实不符」）
    - **不做智能判定。** 只做机械提取，证据行原文照抄。
    - 提取结果一律标「自动提取」，**不声称等于真值**。
    - 否定语义（「撤销」「不授予」）标「可疑」，不静默当成功。
    - 判不出来就标「未核」，**禁止用占位状态填充**。
    - 只读，不修改任何任务卡；不产患者数据。

三列对照
    A 卡头状态   = tasks/T-XXX.md 的 `- **状态**：`
    B 验收记录   = `## 验收记录` 段最后一条状态行（真值优先）
    C 记忆记录   = .workbuddy/memory/MEMORY.md 里 `T-XXX ✅ VERIFIED` 之类
    三者不一致时整行高亮 —— 不一致本身就是要人看的信号。

用法
    python work/lib/build_progress_cards.py
    输出 work/07_cfd_pipeline/workspace/progress-cards.html
    访问 http://127.0.0.1:8769/workspace/progress-cards.html
"""

from __future__ import annotations

import glob
import html
import os
import re
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent                      # work/
ROOT = WORK.parent                      # 项目根
TASKS = ROOT / "tasks"
MEMORY = ROOT / ".workbuddy" / "memory" / "MEMORY.md"
OUT = WORK / "07_cfd_pipeline" / "workspace" / "progress-cards.html"

# 状态词。VERIFIED/CLOSED/EXECUTING/OPEN 是 AGENTS.md 封闭词表；
# 其余是卡片与项目记忆里**实际在用**的写法，照抄不归一化：
#   PARTIAL / BLOCKED / PAUSED  = 记忆里的描述性标记（BLOCKED 由段主使用，
#       AGENTS.md 规定阻塞时状态回退 OPEN、原因记验收记录，故两者可并存）
#   已废弃 / 打回               = 封闭词表内
#   DONE                        = 多张卡卡头自用的「结项」写法（如 T-009/T-010
#       `**✅ DONE**`）。2026-10-15 自查：初版词表漏了 DONE，导致 T-010 被
#       判「未核」。不映射成 CLOSED —— 保留原文用词，避免静默改写语义。
STATUS_WORDS = ("VERIFIED", "CLOSED", "EXECUTING", "OPEN", "PARTIAL",
                "BLOCKED", "PAUSED", "已废弃", "打回", "DONE")
# 出现这些词说明上一句状态被否定 —— 不能当成功
NEGATION = ("撤销", "不授予", "未授予", "作废", "回退", "不是")

STATUS_CLS = {
    "VERIFIED": "ok", "CLOSED": "ok", "DONE": "ok",
    "PARTIAL": "warn", "PAUSED": "warn",
    "BLOCKED": "bad", "已废弃": "bad", "打回": "bad",
    "EXECUTING": "run", "OPEN": "idle", "未核": "unk",
}


def cell(v, cls=""):
    return f'<td class="{cls}">{v}</td>' if cls else f"<td>{v}</td>"


def e(v):
    return html.escape(str(v)) if v is not None else "—"


def read(path):
    if not path.is_file():
        return ""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def pick_card_status(text):
    """A 列：卡头 `- **状态**：`。"""
    m = re.search(r"^-\s*\*\*状态\*\*：(.+)$", text, re.M)
    return m.group(1).strip() if m else None


def pick_acceptance(text):
    """B 列：`## 验收记录` 段最后一条含状态词的行（原文照抄）。"""
    segs = re.findall(r"^##\s*验收记录(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    if not segs:
        return None, None
    lines = [ln.strip() for ln in segs[-1].splitlines() if ln.strip().startswith("-")]
    for ln in reversed(lines):
        if any(w in ln for w in STATUS_WORDS):
            return ln, segs[-1]
    # 段存在但无状态词：给最后一条，让人自己看
    return (lines[-1] if lines else None), segs[-1]


def classify(line):
    """从一行原文里机械提取状态词；含否定词则标可疑。"""
    if not line:
        return "未核", False
    found = [w for w in STATUS_WORDS if w in line]
    if not found:
        return "未核", False
    # 优先取「更靠后」的状态词，因为验收记录常按时间顺序写
    last = found[0]
    for w in STATUS_WORDS:
        if w in line:
            last = w
    suspicious = any(n in line for n in NEGATION)
    return last, suspicious


def parse_memory(text):
    """C 列：MEMORY.md 里 `T-036 ✅ VERIFIED` 模式 → {编号: [(状态, 原文)]}。

    2026-10-15 自查：MEMORY.md 常把多张卡合并在一句里写
    （`T-034/T-035 ✅ VERIFIED`、`T-009✅ / T-010✅`），初版正则只抓前一个
    编号，导致 T-035 / T-010 漏成「—」。现支持 `T-XXX/T-YYY` 连写，两个
    编号都登记同一状态。
    """
    out = {}
    pat = re.compile(
        r"T-(\d{3})(?:\s*/\s*T-(\d{3}))?[^\n]{0,60}?(?:✅|⚠️|⛔|⏸)?[^\n]{0,30}?"
        r"(VERIFIED|CLOSED|PARTIAL|BLOCKED|已废弃|PAUSED|EXECUTING|OPEN)"
    )
    for m in pat.finditer(text):
        status, raw = m.group(3), m.group(0)[:120]
        for gid in (m.group(1), m.group(2)):
            if gid:
                out.setdefault(gid, []).append((status, raw))
    return out


def scan_cards():
    """扫描 tasks/ 与 MEMORY.md，返回卡片字典列表。只读，不修改任何文件。

    供两处复用：① 本脚本的独立进度页 ② 主进度页
    （build_progress_dashboard.py 接回，2026-10-16 用户裁定「接回」）。
    """
    mem = parse_memory(read(MEMORY))
    cards = []
    for path in sorted(glob.glob(str(TASKS / "T-*.md"))):
        name = os.path.basename(path)
        tid = re.match(r"T-(\d{3})", name)
        tid = tid.group(1) if tid else "???"
        text = read(Path(path))
        title = ""
        m = re.search(r"^#\s*(.+)$", text, re.M)
        if m:
            title = re.sub(r"^T-\d+[A-Z-]*\s*·\s*", "", m.group(1)).strip()

        head = pick_card_status(text)
        acc_line, _ = pick_acceptance(text)
        acc_status, suspicious = classify(acc_line)

        # 必须先取记忆：下面「采用」要用到它。
        # 2026-10-15 自查：初版把这三行写在 shown 之后，导致引用的是
        # **上一张卡**的 mem_status —— 静默串号，正是本项目已 7 次出现的
        # 「判据合法但与事实不符」。顺序不可再动。
        mem_hits = mem.get(tid, [])
        mem_status = mem_hits[-1][0] if mem_hits else "—"
        mem_text = mem_hits[-1][1] if mem_hits else "—"

        # 采用优先级：验收记录 > 项目记忆 > 卡头。
        # （卡头最不可信：实测大面积缺失且滞后，T-036 卡头 EXECUTING 而验收
        #   已是 VERIFIED。故卡头只作兜底，仅在前两者都判不出时才用。）
        shown = acc_status
        if head and "已废弃" in head:
            shown = "已废弃"
        elif shown == "未核":
            if mem_status != "—":
                shown = mem_status
            elif head:
                shown, _ = classify(head)

        # 一致性：三列（采用 / 记忆 / 卡头）的状态词是否收敛。
        # 2026-10-15 自查：初版只比「采用 vs 记忆」，漏掉卡头列，
        # 导致 T-036（卡头 EXECUTING / 验收 VERIFIED）被报成「一致 0」——
        # 判据合法但与事实不符。卡头必须参与比较。
        head_word = classify(head)[0] if head else "未核"
        words = set()
        if shown != "未核":
            words.add(shown)
        if mem_status not in ("—", "未核"):
            words.add(mem_status)
        if head_word != "未核":
            words.add(head_word)
        agree = len(words) <= 1

        cards.append({
            "id": name[:-3], "title": title, "head": head,
            "acc_status": acc_status, "acc_line": acc_line,
            "suspicious": suspicious, "shown": shown,
            "mem_status": mem_status, "mem_text": mem_text,
            "agree": agree,
        })

    return cards


def summarize(cards):
    """状态分布统计（不重算、不判定，纯计数）。"""
    counts = {}
    for c in cards:
        counts[c["shown"]] = counts.get(c["shown"], 0) + 1
    return {
        "n": len(cards),
        "counts": counts,
        "n_disagree": sum(1 for c in cards if not c["agree"]),
        "n_susp": sum(1 for c in cards if c["suspicious"]),
        "summary": " ｜ ".join(
            f"{k} <b>{v}</b>"
            for k, v in sorted(counts.items(), key=lambda x: -x[1])
        ),
    }


def main():
    cards = scan_cards()
    st = summarize(cards)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    n = st["n"]
    counts = st["counts"]
    n_disagree = st["n_disagree"]
    n_susp = st["n_susp"]
    summary = st["summary"]

    rows = []
    for c in cards:
        cls = "" if c["agree"] else "disagree"
        rows.append(
            "<tr class=\"%s\">" % cls
            + cell(f'<b>{e(c["id"])}</b>')
            + cell(e(c["title"])[:70])
            + cell(e(c["shown"]), STATUS_CLS.get(c["shown"], "unk"))
            + cell(e(c["head"])[:60] if c["head"] else "（无卡头状态）")
            + cell(e(c["acc_line"])[:150] if c["acc_line"] else "（无验收记录）")
            + cell('<span class="flag">可疑</span>' if c["suspicious"] else "")
            + cell(e(c["mem_status"]), STATUS_CLS.get(c["mem_status"], "unk"))
            + cell(e(c["mem_text"])[:80])
            + "</tr>"
        )

    summary = " ｜ ".join(
        f"{k} <b>{v}</b>" for k, v in sorted(counts.items(), key=lambda x: -x[1])
    )

    page = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>任务卡进度 · 鼻腔 CFD</title>
<style>
/* 令牌与 workspace/pro/tokens.css 同值（单一真源）；chrome 单色，
   状态靠明度 + 字重 + 字形 + 底纹区分，不靠色相。圆角 2–3px 属新版语言。 */
:root{{--bg:#ebebeb;--card:#ffffff;--ink:#1a1a1a;--mut:#6e6e6e;--faint:#9a9a9a;
--line:#dcdcdc;--line2:#c8c8c8;--soft:#f0f0f0;--soft2:#e4e4e4;
--warn:#3d3d3d;--warn-bg:#efefef;--bad:#000000;--bad-bg:#e2e2e2;
--mono:ui-monospace,Consolas,"Cascadia Mono",monospace;color-scheme:light}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
.wrap{{max-width:1500px;margin:0 auto;padding:24px 20px 60px}}
h1{{font-size:22px;margin:0 0 6px}}
.sub{{color:var(--mut);font-size:13px;margin-bottom:18px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:3px;
padding:16px 18px;margin-bottom:16px}}
.warnbox{{border-left:3px solid var(--line2);background:var(--warn-bg)}}
h2{{font-size:16px;margin:0 0 8px}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}
th,td{{border:1px solid var(--line);padding:6px 8px;vertical-align:top;text-align:left}}
th{{background:var(--soft);font-weight:600;position:sticky;top:0}}
tr.disagree{{background:var(--soft2)}}
.ok{{color:var(--ink);font-weight:700;background:var(--soft)}}
.warn{{color:var(--mut);font-weight:700;font-style:italic;background:var(--soft2)}}
.bad{{color:var(--bad);font-weight:700;text-decoration:underline;background:var(--bad-bg)}}
.run{{color:var(--mut)}}
.idle,.unk{{color:var(--faint)}}
.flag{{background:var(--bad-bg);color:var(--bad);padding:1px 6px;border-radius:2px;
border:1px solid var(--line2);font-size:11px}}
code{{background:var(--soft);padding:1px 5px;border-radius:2px;font-size:12px;
font-family:var(--mono)}}
.small{{font-size:12.5px;color:var(--mut)}}
.legend span{{display:inline-block;margin-right:14px;padding:1px 6px;border-radius:2px}}
</style></head><body><div class="wrap">

<h1>任务卡进度 · 鼻腔 CFD 空气域复核</h1>
<div class="sub">生成时间 {now} ｜ 共 <b>{n}</b> 张卡 ｜ 三列对照（卡头 / 验收记录 / 项目记忆）
｜ 不一致行 <b>深底</b> 标出 ｜ 只读，不修改任何任务卡</div>

<div class="card">
<h2>状态分布</h2>
<div>{summary}</div>
<div class="small" style="margin-top:8px">
三列不一致 <b>{n_disagree}</b> 张 ｜ 含否定语义（撤销/不授予）标可疑 <b>{n_susp}</b> 张
</div>
</div>

<div class="card warnbox">
<h2>怎么读这一页（先读，别直接抄状态）</h2>
<p class="small">
<b>1. 本页是机械提取，不声称等于真值。</b>状态词照抄原文，不做语义判定。</p>
<p class="small">
<b>2. 卡头 <code>**状态**</code> 大面积缺失/滞后。</b>实测 38 张卡仅 6 张有卡头状态；
<span class="flag">实证</span> T-036 卡头写 <code>EXECUTING</code>，但验收记录已是
<code>VERIFIED</code>；T-039 卡头 <code>EXECUTING</code>，实际 <code>PARTIAL</code>。
→ <b>验收记录优先于卡头</b>，本脚本已如此取。</p>
<p class="small">
<b>3. 存在否定陷阱。</b>T-040 验收记录里同时有 <code>VERIFIED</code> 和
「此 VERIFIED 已由上方重大修正<b>撤销</b>」——含否定词的行已标
<span class="flag">可疑</span>，请勿当作成功。</p>
<p class="small">
<b>4. 真值以 <code>.workbuddy/memory/MEMORY.md</code> 与
<code>state/状态.md</code> 为准</b>（段主维护，本页 C 列仅作对照）。
旧的 <code>work/进度总览.html</code> 由 <code>build_progress_dashboard.py</code>
生成，该脚本<b>不读 tasks/</b>（只认写死的 T-004/006/008/009/010），已滞后。</p>
</div>

<div class="card">
<h2>全部任务卡</h2>
<div class="small legend" style="margin-bottom:8px">
<span class="ok">完成 = VERIFIED / CLOSED / DONE</span><span class="warn">部分 = PARTIAL</span>
<span class="bad">阻塞 = BLOCKED / 已废弃 / 打回</span><span class="run">进行 = EXECUTING</span>
<span class="idle">未开 = OPEN</span><span class="unk">未核 = 判不出来</span>
<div class="small" style="margin-top:6px">状态词照抄原文、<b>不归一化</b>：
<code>DONE</code> 是多张卡卡头自用的「结项」写法；<code>BLOCKED</code> 是项目记忆里的
描述性标记（AGENTS.md 规定阻塞时状态回退 <code>OPEN</code>、原因记验收记录，
两者可并存，故都保留）。</div>
</div>
<table>
<thead><tr>
<th>卡</th><th>标题</th><th>采用状态</th><th>A · 卡头状态</th>
<th>B · 验收记录（原文）</th><th>可疑</th><th>C · 记忆</th><th>C · 记忆原文</th>
</tr></thead>
<tbody>
{"".join(rows)}
</tbody></table>
</div>

<div class="card"><h2>复现</h2>
<div class="small">
<code>python work/lib/build_progress_cards.py</code><br>
访问 <code>http://127.0.0.1:8769/workspace/progress-cards.html</code>
（走 <code>serve_cfd_workspace.py</code> 默认路由，无需改服务器）<br>
本脚本只读 <code>tasks/</code> 与 <code>.workbuddy/memory/MEMORY.md</code>，
不修改任何任务卡，不碰 <code>build_progress_dashboard.py</code>。
</div></div>

</div></body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"写入 {OUT}")
    print(f"卡片 {n} 张 ｜ 不一致 {n_disagree} ｜ 可疑 {n_susp}")
    print("分布 " + summary)


if __name__ == "__main__":
    main()
