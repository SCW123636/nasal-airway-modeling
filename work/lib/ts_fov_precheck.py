# -*- coding: utf-8 -*-
"""S2.3 预检：三例 FOV 的解剖覆盖 + 骨窗质量。输出 PNG 到 ASCII 路径。"""
import os
import numpy as np
import SimpleITK as sitk
from PIL import Image, ImageDraw

OUT = r"C:\ts_work\preview"
os.makedirs(OUT, exist_ok=True)
info = {}

for k in ["p1", "p2", "p3"]:
    p = rf"C:\ts_work\{k}\ct.nii.gz"
    if not os.path.exists(p):
        continue
    img = sitk.ReadImage(p)
    a = sitk.GetArrayFromImage(img).astype(np.float32)   # (z,y,x) HU
    sp = img.GetSpacing()
    nz, ny, nx = a.shape
    info[k] = {
        "shape": [nz, ny, nx],
        "spacing": [round(v, 4) for v in sp],
        "z_coverage_mm": round((nz - 1) * sp[2], 1),
        "y_coverage_mm": round((ny - 1) * sp[1], 1),
        "x_coverage_mm": round((nx - 1) * sp[0], 1),
        "HU_range": [int(a.min()), int(a.max())],
    }

    def win(sl, lo=-1000, hi=1200):
        return (np.clip((sl - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)

    # 中线矢状位（看前后范围：鼻尖 -> 鼻咽 -> 咽后）
    sag = a[:, :, nx // 2]                 # (z, y)
    # 旁开 25 体素矢状位（看鼻腔/上颌窦）
    dx = max(1, int(25 / sp[0]))
    sag2 = a[:, :, min(nx - 1, nx // 2 + dx)]
    # 冠状位（取 z 中部）
    cor = a[nz // 2, :, :]                 # (y, x)
    # 轴位（取 z 中部）
    axi = a[nz // 2, :, :]

    panels = [
        (win(sag.T), f"{k} sagittal x=mid  (left=anterior?  see axis)"),
        (win(sag2.T), f"{k} sagittal x=mid+25vox"),
        (win(a[nz // 2]), f"{k} axial z={nz//2}"),
    ]
    imgs = []
    for arr, title in panels:
        im = Image.fromarray(arr).convert("RGB")
        d = ImageDraw.Draw(im)
        d.text((6, 6), title, fill=(255, 80, 80))
        d.text((6, 22), f"spacing={ [round(v,3) for v in sp] }  z_cov={(nz-1)*sp[2]:.0f}mm",
               fill=(255, 220, 60))
        imgs.append(im)
    W = sum(i.width for i in imgs) + 20 * (len(imgs) - 1)
    H = max(i.height for i in imgs)
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    x = 0
    for i in imgs:
        canvas.paste(i, (x, 0))
        x += i.width + 20
    canvas.save(os.path.join(OUT, f"{k}_preview.png"))

print("PREVIEW DONE")
for k, v in info.items():
    print(k, v)
