# -*- coding: utf-8 -*-
"""
在鼻孔平面切断空气连通团 (step 2)

思路：
  鼻腔与外部空气的连接只发生在「鼻孔」这个小开口处。
  如果把 y (前后向) 在鼻孔之前的整个平面强制设为「非空气」，
  则外部空气与鼻腔被硬性断开 → 鼻腔成为独立连通体。

关键：找到正确的鼻孔切割平面 y_cut。
  做法：对每个 y 平面，统计该平面上空气在「鼻腔 x 范围」内的占比；
  真鼻孔处会出现一个窄而明显的通道。

输出：多张诊断 PNG + JSON
"""
import os, json
import numpy as np
from PIL import Image
from scipy import ndimage

OUT = r"C:\nasal_probe"
arr = np.load(os.path.join(OUT, "vol_zyx.npy"))       # (z,y,x) HU
nz, ny, nx = arr.shape
report = {"shape": [nz, ny, nx]}

# 已知解剖锚点（来自上一轮 anatomy_locate，z 大=上，y 大=后）
# 鼻尖 z≈120 y≈43 ; 鼻腔 x≈189-227 ; 中心 x=256
# 现在用 z=150~200 这段（鼻腔本部）来看 y 方向走行

air = (arr > -1100) & (arr < -300)

# ---- 逐 y 统计：在鼻腔 x 窗口内，空气的连通"宽度" ----
xc_lo, xc_hi = 150, 300          # 放宽的鼻腔 x 搜索窗
rows = []
for y in range(0, ny):
    sl = air[:, y, xc_lo:xc_hi]
    cnt = int(sl.sum())
    rows.append(cnt)

rows = np.array(rows)
np.save(os.path.join(OUT, "y_aircount.npy"), rows)

# 找「前段低、后段高」的拐点候选
# 前段（y<60）应是面部外空气；鼻腔应从鼻孔后开始
cand = []
for y in range(10, 200):
    before = rows[max(0, y - 12):y].mean()
    after = rows[y:y + 12].mean()
    if after > before * 2.2 and after > 150:
        cand.append({"y": y, "before": round(float(before), 1),
                     "after": round(float(after), 1),
                     "jump_ratio": round(float(after / max(before, 1e-6)), 2)})
report["y_candidates"] = cand[:20]

# ---- 可视化 y 曲线（纯 PIL，无 matplotlib 依赖） ----
from PIL import ImageDraw, ImageFont
W, H, PAD = 1400, 420, 50
canvas = Image.new("RGB", (W, H), (255, 255, 255))
dr = ImageDraw.Draw(canvas)
# 坐标轴
dr.line([(PAD, H - PAD), (W - 20, H - PAD)], fill=(0, 0, 0), width=2)
dr.line([(PAD, 20), (PAD, H - PAD)], fill=(0, 0, 0), width=2)
ymax = float(rows.max()) if rows.max() > 0 else 1.0
sx = (W - 20 - PAD) / max(1, len(rows) - 1)
sy = (H - PAD - 20) / ymax
pts = [(PAD + i * sx, H - PAD - float(v) * sy) for i, v in enumerate(rows)]
dr.line(pts, fill=(30, 90, 200), width=2)
# 标出候选 y
for c in cand[:8]:
    x = PAD + c["y"] * sx
    dr.line([(x, 20), (x, H - PAD)], fill=(220, 40, 40), width=1)
    dr.text((x + 2, 24), str(c["y"]), fill=(220, 40, 40))
dr.text((PAD, 4), "air count in x[150,300] vs y  (y large = posterior)", fill=(0, 0, 0))
dr.text((PAD, H - PAD + 8), "y=0", fill=(0, 0, 0))
dr.text((W - 60, H - PAD + 8), f"y={len(rows)-1}", fill=(0, 0, 0))
canvas.save(os.path.join(OUT, "y_aircount.png"))

# ---- 渲染若干矢状位（沿鼻中隔 x≈256 附近）看气道 ----
def win(sl):
    lo, hi = -500, 1500
    return (np.clip((sl.astype(np.float32) - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)

for x in (215, 235, 256, 275, 295):
    sag = arr[:, :, x]                     # (z, y)
    u8 = win(sag)
    # 叠加空气掩膜（红）
    m = air[:, :, x]
    rgb = np.stack([u8, u8, u8], -1)
    rgb[m] = [255, 60, 60]
    Image.fromarray(rgb).resize((ny * 2, nz * 2), Image.NEAREST).save(
        os.path.join(OUT, f"sag_air_x{x}.png"))

# 轴位关键层
for z in (130, 150, 170, 190, 210):
    ax_sl = arr[z]
    u8 = win(ax_sl)
    m = air[z]
    rgb = np.stack([u8, u8, u8], -1)
    rgb[m] = [255, 60, 60]
    Image.fromarray(rgb).save(os.path.join(OUT, f"axi_air_z{z}.png"))

report["ok"] = True
with open(os.path.join(OUT, "y_axis_probe.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print("DONE")
