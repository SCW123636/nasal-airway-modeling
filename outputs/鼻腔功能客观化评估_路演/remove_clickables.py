# -*- coding: utf-8 -*-
"""删除 deck 中所有可点击元素（用户裁定 2026-10-16 18:20）。

- 删除所有「▸ …」行内链接芯片形状（任意页）
- 删除附录页（标题含「可点开的材料」）
- 兜底：清除所有残余 run 级超链接（保留下划线样式一并去掉）
用法: python remove_clickables.py <deck.pptx>
"""
import sys
from pptx import Presentation

deck = sys.argv[1]
prs = Presentation(deck)

n_chip = 0
n_hl = 0
appendix_idx = None
for i, slide in enumerate(list(prs.slides)):
    # 删芯片
    for shape in list(slide.shapes):
        if shape.has_text_frame and shape.text_frame.text.strip().startswith("▸ "):
            shape._element.getparent().remove(shape._element)
            n_chip += 1
    # 定位附录页
    full = " ".join(sh.text_frame.text for sh in slide.shapes if sh.has_text_frame)
    if "可点开的材料" in full:
        appendix_idx = i
    # 兜底清超链接
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        for para in shape.text_frame.paragraphs:
            for run in para.runs:
                if run.hyperlink.address is not None:
                    run.hyperlink.address = None
                    run.font.underline = False
                    n_hl += 1

# 删附录页（从后往前删避免索引位移；此处最多一页）
if appendix_idx is not None:
    xml_slides = prs.slides._sldIdLst
    sld = list(xml_slides)[appendix_idx]
    rId = sld.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    prs.part.drop_rel(rId)
    xml_slides.remove(sld)

prs.save(deck)

# 回读验证
prs2 = Presentation(deck)
bad_hl = 0
chips = 0
appendix = 0
for s in prs2.slides:
    for shape in s.shapes:
        if shape.has_text_frame:
            t = shape.text_frame.text.strip()
            if t.startswith("▸ "): chips += 1
            if "可点开的材料" in t: appendix += 1
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    if run.hyperlink.address: bad_hl += 1
print(f"{deck}: 页数={len(prs2.slides)}  删芯片={n_chip}  清超链={n_hl}  删附录页={1 if appendix_idx is not None else 0}"
      f"  || 残留: 芯片{chips} 超链{bad_hl} 附录{appendix}")
