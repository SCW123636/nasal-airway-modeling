# -*- coding: utf-8 -*-
"""行内附件链接芯片 + 封面队伍/序号徽标 + 封面去患者数表述。

- 芯片：目标页顶部右侧留白带（y 1–23px，右缘对齐版心 1216px），
  小号青色下划线文本，整块可点，指向 附件/ 相对路径或 Demo 本地服务。
- 封面：右上角「剑穹小队 · 演讲序号 02」；「三例患者…」表述按要求移除。
- 可重复运行（芯片按文本前缀判重，徽标按「剑穹小队」判重）。

用法: python add_inline_links.py <deck.pptx> <full|4min>
"""
import sys
from pptx import Presentation
from pptx.util import Emu, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor

LINK_RESEARCH = "附件/01-患者需求调研/索引.html"
LINK_DEMO = "http://localhost:8769/workspace/pro/index.html"
LINK_CALIB = "附件/03-标定与基准计划/从24例到标准_训练设计_v1.html"

# 页码（1 起）-> (芯片文本, 链接目标)
PAGE_MAP = {
    "full": {4: ("患者需求调研包", LINK_RESEARCH),
             5: ("患者需求调研包", LINK_RESEARCH),
             7: ("现场 Demo 入口", LINK_DEMO),
             14: ("标定与基准计划", LINK_CALIB),
             15: ("标定与基准计划", LINK_CALIB)},
    "4min": {3: ("患者需求调研包", LINK_RESEARCH),
             4: ("患者需求调研包", LINK_RESEARCH),
             5: ("现场 Demo 入口", LINK_DEMO),
             6: ("标定与基准计划", LINK_CALIB),
             7: ("标定与基准计划", LINK_CALIB)},
}

COVER_REPLACE = [("三例患者全链跑通", "全链路可复现"),
                 ("2026.10 · 三例患者全链验证", "2026.10 · 全链路验证")]


def add_chip(slide, text, target):
    # 先移除旧版芯片（可重复运行；旧几何贴顶会被裁切）
    for shape in list(slide.shapes):
        if shape.has_text_frame and shape.text_frame.text.strip().startswith("▸ "):
            shape._element.getparent().remove(shape._element)
    # 放在页眉徽标（x 1170–1216, y 24–70）左侧同一行：右缘 1150px，y 34–60px
    box = slide.shapes.add_textbox(Emu(7953750), Emu(323850), Emu(3000000), Emu(250000))
    tf = box.text_frame
    tf.word_wrap = False
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.RIGHT
    run = p.add_run()
    run.text = "▸ " + text
    f = run.font
    f.size = Pt(10.5)
    f.underline = True
    f.color.rgb = RGBColor(0x7F, 0xD4, 0xEA)
    run.hyperlink.address = target
    return True


def add_cover_badge(slide):
    for shape in slide.shapes:
        if shape.has_text_frame and "剑穹小队" in shape.text_frame.text:
            return False  # 已存在
    box = slide.shapes.add_textbox(Emu(8306200), Emu(609600), Emu(3200000), Emu(300000))
    tf = box.text_frame
    tf.word_wrap = False
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.RIGHT
    r1 = p.add_run()
    r1.text = "剑穹小队"
    r1.font.size = Pt(15)
    r1.font.bold = True
    r1.font.color.rgb = RGBColor(0xE8, 0xF1, 0xFA)
    r2 = p.add_run()
    r2.text = "　·　演讲序号 02"
    r2.font.size = Pt(13)
    r2.font.color.rgb = RGBColor(0x22, 0xD3, 0xEE)
    return True


def replace_text(slide, old, new):
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        for para in shape.text_frame.paragraphs:
            full = "".join(r.text for r in para.runs)
            if old in full:
                runs = para.runs
                runs[0].text = full.replace(old, new)
                for r in runs[1:]:
                    r.text = ""
                return True
    return False


deck, kind = sys.argv[1], sys.argv[2]
prs = Presentation(deck)
slides = list(prs.slides)

n_chip = 0
for page_no, (text, target) in PAGE_MAP[kind].items():
    if add_chip(slides[page_no - 1], text, target):
        n_chip += 1

badge = add_cover_badge(slides[0])

n_rep = 0
for old, new in COVER_REPLACE:
    if replace_text(slides[0], old, new):
        n_rep += 1

prs.save(deck)

# 回读验证
prs2 = Presentation(deck)
links = {}
for i, s in enumerate(prs2.slides, 1):
    for shape in s.shapes:
        if shape.has_text_frame:
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    a = run.hyperlink.address
                    if a:
                        links.setdefault(i, set()).add(a)
chip_pages = {p: len(v) for p, v in links.items() if p != len(prs2.slides)}
print(f"{deck}: 新增芯片 {n_chip}/{len(PAGE_MAP[kind])}, 徽标新增={badge}, 封面替换 {n_rep}/{len(COVER_REPLACE)}")
print("  各页链接分布:", {p: len(v) for p, v in sorted(links.items())})
