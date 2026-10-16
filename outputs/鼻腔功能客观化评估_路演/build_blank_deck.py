"""为路演 deck 生成 18 页空白 16:9 母版，供 slidep upsert-dsl 逐页替换。

背景：slidep create 产出的 pptx 只含 1 页，追加第 2 页会触发
CommitRevision [13006] page index out of range。故先用 python-pptx 预置 N 页空白页，
再按 index 逐页 upsert。
"""
import sys

from pptx import Presentation
from pptx.util import Emu

# 用法: python build_blank_deck.py [页数] [输出路径]（缺省 = 18 页 / 主 deck）
N_PAGES = int(sys.argv[1]) if len(sys.argv) > 1 else 18
OUT = (sys.argv[2] if len(sys.argv) > 2
       else r"D:\项目\鼻腔建模\outputs\鼻腔功能客观化评估_路演\鼻腔功能客观化评估_路演.pptx")

# 16:9 —— 与 DSL 画布 1280x720 同比例
SLIDE_W = Emu(12192000)
SLIDE_H = Emu(6858000)

prs = Presentation()
prs.slide_width = SLIDE_W
prs.slide_height = SLIDE_H

# 默认模板中 index 6 = Blank
blank = prs.slide_layouts[6]

# 删除默认模板自带的首页，改为全部空白
xml_slides = prs.slides._sldIdLst
for sld in list(xml_slides):
    rId = sld.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    prs.part.drop_rel(rId)
    xml_slides.remove(sld)

for _ in range(N_PAGES):
    prs.slides.add_slide(blank)

prs.save(OUT)

# 复核
chk = Presentation(OUT)
print("saved:", OUT)
print("slide_count:", len(chk.slides._sldIdLst))
print("size(EMU):", chk.slide_width, chk.slide_height)
for i, s in enumerate(chk.slides):
    shapes = len(s.shapes)
    assert shapes == 0, f"page {i} not blank: {shapes} shapes"
print("all pages blank: OK")
