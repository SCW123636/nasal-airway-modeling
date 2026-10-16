# -*- coding: utf-8 -*-
"""调研汇总同步脚本：原件更新后重跑本脚本，刷新 调研汇总/ 全部内容。

- 不动原件（knowledge/患者需求 = 需求归口；outputs/* = 执行产物），本目录只是检索层。
- 全部 .md 转 HTML（含内部 .md 链接改 .html），txt/json 原样拷贝。
- 重新生成 index.html（即时搜索检索页）。
用法: python "D:/项目/鼻腔建模/调研汇总/sync_调研汇总.py"
"""
import os, glob, shutil, json, re
import markdown

ROOT = r"D:\项目\鼻腔建模"
DST = os.path.join(ROOT, "调研汇总")

CSS = """<meta charset="utf-8"><title>{t}</title>
<style>
body{{font-family:"Microsoft YaHei",sans-serif;max-width:960px;margin:32px auto;padding:0 24px;line-height:1.75;color:#1c2733;}}
h1{{border-bottom:2px solid #0e7490;padding-bottom:8px;color:#0c4a6e;}} h2{{color:#0c4a6e;}}
table{{border-collapse:collapse;margin:16px 0;}} th,td{{border:1px solid #cbd5e1;padding:6px 12px;}} th{{background:#f1f5f9;}}
code{{background:#f1f5f9;padding:2px 6px;border-radius:3px;}} a{{color:#0e7490;}}
.src{{background:#f8fafc;border-left:4px solid #0e7490;padding:8px 14px;color:#475569;font-size:13px;margin-top:24px;}}
</style>"""

def md2html(md_path, html_path, source_note):
    txt = open(md_path, encoding="utf-8").read()
    body = markdown.markdown(txt, extensions=["tables", "fenced_code"])
    # 内部链接统一落 HTML：.md/.txt -> .html（预览服务对 txt 返回 Forbidden）
    body = re.sub(r'href="([^"]+)\.(?:md|txt)"', r'href="\1.html"', body)
    # 死链防护：相对链接目标不存在时降级为纯文本（保留文字）
    base_dir = os.path.dirname(html_path)
    def _dead(m):
        href = m.group(1)
        if href.startswith(("http", "#", "mailto:")): return m.group(0)
        target = os.path.normpath(os.path.join(base_dir, href.split("#")[0]))
        return m.group(2) if not os.path.exists(target) else m.group(0)
    body = re.sub(r'<a href="([^"]+)">([^<]*)</a>', _dead, body)
    title = os.path.splitext(os.path.basename(md_path))[0]
    open(html_path, "w", encoding="utf-8").write(
        f'<!DOCTYPE html><html><head>{CSS.format(t=title)}</head><body>{body}'
        f'<div class="src">原件：{source_note}</div></body></html>')

items = []

def txt2html(txt_path, html_path, source_note, title):
    txt = open(txt_path, encoding="utf-8").read()
    esc = txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    open(html_path, "w", encoding="utf-8").write(
        f'<!DOCTYPE html><html><head>{CSS.format(t=title)}</head><body><h1>{title}</h1>'
        f'<pre style="white-space:pre-wrap;word-break:break-word;font-family:inherit;">{esc}</pre>'
        f'<div class="src">原件：{source_note}</div></body></html>')

# (原件路径, 汇总内相对路径, 标题, 日期, 说明) —— 保留 原始材料/ 子目录结构与原件一致
meta1 = [
    ("knowledge/患者需求/索引.md", "01-患者需求调研/索引.html",
     "患者需求材料索引（需求归口总目录）", "2026-10-15", "需求类材料唯一归口的登记表与交叉核对"),
    ("knowledge/患者需求/20261015-鼻腔建模-患者需求交叉分析.md", "01-患者需求调研/20261015-鼻腔建模-患者需求交叉分析.html",
     "患者需求交叉分析（需求→CFD指标映射）", "2026-10-15", "鼻阻力/WSS/后鼻孔温湿/热通量与需求的对应矩阵"),
    ("knowledge/患者需求/20261015-补充信息记录与准确性评估.md", "01-患者需求调研/20261015-补充信息记录与准确性评估.html",
     "补充信息记录与准确性评估", "2026-10-15", "用户口述转记，L1/L2/L3 证据分级"),
    ("knowledge/患者需求/20261016-ENS定制鼻塞-患者需求与实现条件.md", "01-患者需求调研/20261016-ENS定制鼻塞-患者需求与实现条件.html",
     "ENS 定制鼻塞：需求 × 实现条件（第二轮外部调研）", "2026-10-16", "逐字入库；【实】/【推】/【误】/【空】标注"),
    ("knowledge/患者需求/20261016-ENS其他解决方案与跨界借鉴.md", "01-患者需求调研/20261016-ENS其他解决方案与跨界借鉴.html",
     "ENS 其他解决方案 × 跨界借鉴（第三轮外部调研）", "2026-10-16", "填充之外的路线；N1–N5 待核引用"),
    ("knowledge/患者需求/原始材料/空鼻症患者共性问题交叉验证表.md", "01-患者需求调研/原始材料/空鼻症患者共性问题交叉验证表.html",
     "空鼻症患者共性问题交叉验证表（原始·SRC-A）", "2026-10-15", "群体共性，多源文献交叉验证"),
    ("knowledge/患者需求/原始材料/患者真实需求_聊天记录复述.txt", "01-患者需求调研/原始材料/患者真实需求_聊天记录复述.html",
     "患者真实需求·聊天记录复述（原始·SRC-B）", "2026-10-15", "个体患者自述，去标识化"),
]
for src, rel, title, date, desc in meta1:
    full_src = os.path.join(ROOT, src)
    dst = os.path.join(DST, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if src.endswith(".md"):
        md2html(full_src, dst, src)
    else:  # txt 转 html（检索层不留 txt：预览服务对 txt 返回 Forbidden）
        txt2html(full_src, dst, src, title)
    items.append(("患者需求调研", title, date, desc, rel, src))

meta2 = [
    ("report.md", "症状关联与小样本方法学·总报告", "2026-10-16", "症状关联证据分级：SAHF50 r≈−0.76 > 下鼻道WSS −0.398 > 中鼻道气流 0.76 > 前端温降"),
    ("report_题5题6_S4方法学.md", "补充报告：题5题6 S4 方法学", "2026-10-16", "无监督表型聚类的方法学细节"),
    ("report_题7题8题9_S4执行前补全.md", "补充报告：题7–9 S4 执行前补全", "2026-10-16", "S4 升格主线前的补全调研"),
    ("S4文献登记表_v1.md", "S4 文献登记表 v1", "2026-10-16", "症状映射文献逐篇登记"),
]
folder = "outputs/20261016-云端调研_症状关联与小样本方法学"
for rel_name, title, date, desc in meta2:
    src = f"{folder}/{rel_name}"
    md2html(os.path.join(ROOT, src),
            os.path.join(DST, "02-云端调研_症状关联与小样本方法学", rel_name[:-3] + ".html"), src)
    items.append(("云端调研·症状关联与小样本", title, date, desc,
                  "02-云端调研_症状关联与小样本方法学/" + rel_name[:-3] + ".html", src))
for j in glob.glob(os.path.join(ROOT, folder, "results", "*.json")):
    shutil.copyfile(j, os.path.join(DST, "02-云端调研_症状关联与小样本方法学/原始证据json", os.path.basename(j)))

src = "outputs/20261016-B患者症状痕迹探查/探查报告.md"
md2html(os.path.join(ROOT, src), os.path.join(DST, "03-B患者症状痕迹探查/探查报告.html"), src)
items.append(("B患者症状痕迹探查", "B 患者症状痕迹探查报告", "2026-10-16",
              "30 例 DICOM 挖掘零痕迹 → 与病历/采集双断互证，S2 关闭的依据之一",
              "03-B患者症状痕迹探查/探查报告.html", src))
shutil.copyfile(os.path.join(ROOT, "outputs/20261016-B患者症状痕迹探查/probe_result.json"),
                os.path.join(DST, "03-B患者症状痕迹探查/probe_result.json"))

# ---- 04 技术详细链路（CT → 功能数字 全链方法文档）----
meta4 = [
    ("work/07_cfd_pipeline/正常路径基本方法_v1.md",
     "【总览·权威SOP】正常路径基本方法 v1", "2026-10-12",
     "全链现行方法标准：DICOM→几何→网格→求解→指标 各阶段步骤、判据与禁改项"),
    ("work/07_cfd_pipeline/当前进度与使用说明.md",
     "【总览】当前进度与使用说明", "2026-10-16",
     "各阶段完成度与工作台启动方式（8769 / 启动三维工作台.ps1）"),
    ("knowledge/结论卡/20261016-T-058-出口解剖斜切与三维检视.md",
     "【几何层】T-058 扩展域流水线 v2 与出口斜切", "2026-10-16",
     "现行几何链：5 脚本流水线 + 口咽扩展域工程截断出口 + 三例全链验证（§6 数据基线）"),
    ("work/07_cfd_pipeline/18Pa与边界条件修订.md",
     "【求解层】18 Pa 与边界条件修订", "2026-10-15",
     "出口端 gauge 静压口径（非 Δp）与边界条件演进；D-0′ 自然分流裁定前的口径记录"),
    ("knowledge/结论卡/20261016-T-054-b15口咽扩展域重定基.md",
     "【求解层】T-054 b15 扩展域重定基", "2026-10-16",
     "新域标准首例全链数字：Δp 18.267 Pa / R 0.07307 / WSS 1.506e-3 N；短域低估 43.7%"),
    ("knowledge/结论卡/20261016-T-042-患者功能指标首产.md",
     "【指标层】T-042 患者功能指标首产", "2026-10-16",
     "R / Δp / WSS 三类指标的定义、提取截面与计算脚本链路"),
    ("knowledge/结论卡/20261016-T-057-b15扩展域流线重追踪与工作台接入.md",
     "【可视化层】T-057 扩展域流线与工作台接入", "2026-10-16",
     "收敛场流线重追踪 + 工作台流线页接通 + 出口参数化（治本）"),
    ("work/07_cfd_pipeline/CFD配置与结果契约.md",
     "【契约】CFD 配置与结果契约", "2026-10-15",
     "numerical_validation 三态、engineering_screen 判据、8 份配置执行门"),
]
for src, title, date, desc in meta4:
    rel = "04-技术详细链路/" + title.split("]")[0].strip("[") + "_" + os.path.basename(src)[:-3] + ".html"
    os.makedirs(os.path.join(DST, "04-技术详细链路"), exist_ok=True)
    md2html(os.path.join(ROOT, src), os.path.join(DST, rel), src)
    items.append(("技术详细链路", title, date, desc, rel, src))

# ---- 05 验证与校准依据（PPT「为什么这些数字可以被相信」三道门的底稿）----
meta5 = [
    ("tasks/T-002.md",
     "【门①已知答案对照】T-002 数值隔离基准", "2026-10-14",
     "wedge 压降偏差 1.312%、流量 6.4e-14；2D Poiseuille 2.17/0.61/0.18% —— 数值模板标定的基准题"),
    ("knowledge/结论卡/20261015-T-036-圆管9格纯数值轴判别.md",
     "【门①已知答案对照】T-036 圆管 9 格纯数值轴判别", "2026-10-15",
     "纯数值轴盲测：求解器在已知解析解的圆管算例上的判别记录"),
    ("knowledge/结论卡/20261015-T-037-退化网格阳性对照.md",
     "【门①已知答案对照】T-037 退化网格阳性对照", "2026-10-15",
     "阳性对照：故意喂退化网格，验证判据真的会报警（判据灵敏度测试）"),
    ("work/07_cfd_pipeline/风见方法对照与隔离验证.md",
     "【门①已知答案对照】风见方法对照与隔离验证", "2026-10-08",
     "与外部方法（风见）逐步对照，隔离验证几何/求解各环节无串味"),
    ("work/07_cfd_pipeline/正常路径验收报告_b01-b24_20261012.md",
     "【门②独立复验】正常路径验收报告 b01–b24", "2026-10-12",
     "按同一套判据对全队列逐项验收的记录（未参与创作者可复核的底稿）"),
    ("tasks/T-042.md",
     "【门③一条命令复现】T-042 指标复算任务卡", "2026-10-16",
     "删掉旧现场从原始案例重建：42 秒完成，12 个已知值 + 6 个输入 SHA256 逐位匹配"),
]
for src, title, date, desc in meta5:
    rel = "05-验证与校准依据/" + os.path.basename(src)[:-3] + ".html"
    os.makedirs(os.path.join(DST, "05-验证与校准依据"), exist_ok=True)
    md2html(os.path.join(ROOT, src), os.path.join(DST, rel), src)
    items.append(("验证与校准依据", title, date, desc, rel, src))

# ---- 06 标准训练方法（从 24 例到标准的路线设计）----
meta6 = [
    ("plan/从24例到标准_训练设计_v1.md",
     "《从 24 例到标准》训练设计 v1（主文档）", "2026-10-16",
     "17 章：数据三现实 / 症状对应主线 / 四主特征 + S1 常模 / S4 无监督表型聚类（k 裁定·文献映射·禁个体化预测）/ A→D 路线图 / §10 云端调研回执"),
    ("plan/20261016-云端调研任务书_症状关联与小样本方法学.md",
     "云端调研任务书：症状关联与小样本方法学", "2026-10-16",
     "训练设计调研环节的任务书（输出即 02 分类里的四份报告与证据 json）"),
]
for src, title, date, desc in meta6:
    rel = "06-标准训练方法/" + os.path.basename(src)[:-3] + ".html"
    os.makedirs(os.path.join(DST, "06-标准训练方法"), exist_ok=True)
    md2html(os.path.join(ROOT, src), os.path.join(DST, rel), src)
    items.append(("标准训练方法", title, date, desc, rel, src))

# 06 补充：未来计划（P17 愿景）的队列就绪依据 —— 24 例批量实跑记录
import json as _json
t059_card = "tasks/T-059.md"
rel = "06-标准训练方法/T-059_24例扩展域批量任务卡.html"
md2html(os.path.join(ROOT, t059_card), os.path.join(DST, rel), t059_card)
items.append(("标准训练方法", "【队列就绪依据】T-059 · 24 例扩展域几何批量任务卡", "2026-10-16",
              "24 例批量重跑的立约卡：合同、输入实测、唯一执行命令、禁改清单", rel, t059_card))

jpath = os.path.join(ROOT, "outputs/T-059/normal_run_t059.json")
jdata = _json.load(open(jpath, encoding="utf-8"))
summary_rows = "".join(
    f"<tr><th>{k}</th><td>{_json.dumps(v, ensure_ascii=False)}</td></tr>"
    for k, v in jdata.items() if not isinstance(v, (dict, list)))
jbody = (f'<h1>normal_run_t059.json · 24 例批量运行结果（机读报告）</h1>'
         f'<p>愿景页「24 例队列已就绪」的直接出处：<b>{jdata.get("cases")}</b> 例、'
         f'<b>{jdata.get("auto_pass")}</b> 例 auto_pass（T-059 批量，扩展域口径）。</p>'
         f'<table>{summary_rows}</table>'
         f'<h2>完整 JSON</h2>'
         f'<pre style="white-space:pre-wrap;word-break:break-word;background:#f8fafc;padding:14px;border-radius:6px;'
         f'font-size:12.5px;">{_json.dumps(jdata, ensure_ascii=False, indent=1)}</pre>'
         f'<div class="src">原件：outputs/T-059/normal_run_t059.json（逐例明细在 rows 字段；surfaces/ openings/ 为几何产物）</div>')
open(os.path.join(DST, "06-标准训练方法", "T-059_24例批量运行结果.html"), "w", encoding="utf-8").write(
    f'<!DOCTYPE html><html><head>{CSS.format(t="T-059 24例批量运行结果")}</head><body>{jbody}</body></html>')
items.append(("标准训练方法", "【队列就绪依据】T-059 · 24 例批量运行结果（23/24 auto_pass）", "2026-10-16",
              "机读结果可视化：24 例、23 例过全部表面判据、扩展域（鼻+鼻咽+口咽）；含逐例明细 rows",
              "06-标准训练方法/T-059_24例批量运行结果.html", "outputs/T-059/normal_run_t059.json"))

# ---- index.html ----（分类顺序 = 路演 PPT 叙事顺序：需求 → 方案 → 验证 → 未来）
cats = ["患者需求调研", "技术详细链路", "验证与校准依据", "云端调研·症状关联与小样本", "B患者症状痕迹探查", "标准训练方法"]
ppt_tag = {
    "患者需求调研": "路演 P03–05 · 问题与需求",
    "技术详细链路": "路演 P07 · 产品与解决方案",
    "验证与校准依据": "路演 P14–15 · 测试过程与真实反馈",
    "云端调研·症状关联与小样本": "路演 P17 · 未来计划（愿景证据）",
    "B患者症状痕迹探查": "路演 P17 前提 · 症状标签不可得的依据",
    "标准训练方法": "路演 P17 · 未来计划（从评估工具到标准的路线）",
}
rows = ""
for ci, cat in enumerate(cats, 1):
    rows += (f'<h2 id="cat-{ci:02d}">{cat} <span class="cnt">{sum(1 for i in items if i[0]==cat)} 份 · '
             f'{ppt_tag[cat]}</span></h2>\n')
    if cat == "技术详细链路":
        rows += ('<div class="flow">DICOM 数据 → 几何（分段/表面/开口/扩展域）→ 网格（netgen）→ 求解（simpleFoam 层流）'
                 '→ 指标（R / Δp / WSS）→ 可视化与工作台 —— 按链路顺序排列，⭐ 从「总览·权威SOP」读起</div>\n')
    if cat == "验证与校准依据":
        rows += ('<div class="flow">对应路演页「为什么这些数字可以被相信」的验证三重门：'
                 '门① 已知答案对照（解出来的力和输入对得上）→ 门② 独立复验（不是自己给自己签字）→ '
                 '门③ 一条命令复现（别人能重来一遍）—— 每张卡标注它支撑哪道门</div>\n')
    for _, title, date, desc, link, src in items:
        if _ != cat: continue
        ext = "（原始文本）" if link.endswith(".txt") else ""
        rows += (f'<div class="card" data-k="{title} {desc} {date}">'
                 f'<a href="{link}">{title}</a>{ext}<span class="date">{date}</span>'
                 f'<div class="desc">{desc}</div><div class="src2">原件：{src}</div></div>\n')

index = f'''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>调研汇总检索</title>
<style>
body{{font-family:"Microsoft YaHei",sans-serif;max-width:980px;margin:24px auto;padding:0 24px;color:#1c2733;line-height:1.6;}}
h1{{color:#0c4a6e;border-bottom:3px solid #0e7490;padding-bottom:10px;}}
#q{{width:100%;box-sizing:border-box;font-size:17px;padding:12px 16px;border:2px solid #0e7490;border-radius:8px;margin:18px 0 8px;}}
.hint{{color:#64748b;font-size:13px;margin-bottom:20px;}}
h2{{color:#0c4a6e;margin-top:34px;}} .cnt{{font-size:13px;color:#64748b;font-weight:normal;}}
.card{{border:1px solid #e2e8f0;border-left:4px solid #0e7490;border-radius:6px;padding:12px 16px;margin:10px 0;background:#fff;}}
.card a{{font-size:17px;font-weight:bold;color:#0e7490;text-decoration:none;}} .card a:hover{{text-decoration:underline;}}
.date{{float:right;color:#94a3b8;font-size:13px;}} .desc{{color:#475569;font-size:14px;margin-top:4px;}}
.src2{{color:#94a3b8;font-size:12px;margin-top:4px;}}
.gap{{background:#fef9c3;border-left:4px solid #ca8a04;padding:10px 14px;font-size:14px;color:#713f12;border-radius:4px;}}
.flow{{background:#ecfeff;border-left:4px solid #0891b2;padding:10px 14px;font-size:13.5px;color:#155e75;border-radius:4px;margin-bottom:14px;}}
</style></head><body>
<h1>调研汇总 · 检索页</h1>
<input id="q" placeholder="🔍 输入关键词即时过滤（如：鼻塞 / WSS / 量表 / 探查 / 2026-10-15）…">
<div class="hint">共 {len(items)} 份材料 · 本页为检索入口，<b>原件均未移动</b>（每张卡片底部标注原件路径）；修改原件后重跑本目录 sync_调研汇总.py 即可刷新。</div>
<div class="gap">⚠️ 已知缺口：第一轮《空鼻症鼻腔填充与定制器件全谱系深度调研报告》原文<b>未在本项目落盘</b>；第二轮文首 E1/E2/E3 更正针对它，读第二轮时须知道被更正的原文不在本地。</div>
{rows}
<script>
document.getElementById("q").addEventListener("input", e => {{
  const k = e.target.value.trim().toLowerCase();
  document.querySelectorAll(".card").forEach(c => {{
    c.style.display = !k || c.dataset.k.toLowerCase().includes(k) ? "" : "none";
  }});
}});
</script>
</body></html>'''
open(os.path.join(DST, "index.html"), "w", encoding="utf-8").write(index)
json.dump(items, open(os.path.join(DST, "_items.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"同步完成：{len(items)} 份材料 + index.html")
