# -*- coding: utf-8 -*-
"""生成自包含 HTML 复核页：三向切片 + 掩膜/体内空气/标定锚点叠加
数据内嵌(base64 PNG)，单文件可离线打开
"""
import os, sys, json, base64, io
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series, window_ct

ROOT = r"D:\项目\鼻腔建模"
DICOM = os.path.join(ROOT, "work", "00_dicom", "bone")
SEG = os.path.join(ROOT, "work", "02_segment")
CAL = os.path.join(ROOT, "work", "03_calib")

vol, sp, org, meta = load_dicom_series(DICOM, verbose=False)
nz, ny, nx = vol.shape
dx, dy, dz = sp
air = vol < -300

# 体内/体外
from scipy import ndimage
outside = np.zeros_like(air)
for z in range(nz):
    a = air[z]
    if not a.any():
        continue
    lbl, n = ndimage.label(a, structure=np.ones((3, 3)))
    el = set(lbl[0, :]) | set(lbl[-1, :]) | set(lbl[:, 0]) | set(lbl[:, -1])
    el.discard(0)
    if el:
        outside[z] = np.isin(lbl, list(el))
inside = air & (~outside)

mask_v9 = np.load(os.path.join(SEG, "nasal_mask_v9.npy"))
lm = json.load(open(os.path.join(CAL, "landmarks.json"), encoding="utf-8"))
A = lm["anchors"]
z_nos = A["z_nostril_entry"]["z"]
z_pk = A["z_nasal_peak"]["z"]
z_nas = A["z_nasopharynx"]["z"]

def b64(img, scale=0.5):
    """缩到 256x256 再存，控制体积"""
    h, w = img.shape[:2]
    im = Image.fromarray(img).resize((int(w * scale), int(h * scale)),
                                     Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()

# ---- 轴位切片（全身范围，每 2 层） ----
def axial_rgb(z):
    u8 = window_ct(vol[z], 800, 2000)
    rgb = np.stack([u8] * 3, axis=-1).copy()
    rgb[inside[z]] = [255, 80, 80]        # 体内空气 红
    rgb[mask_v9[z]] = [255, 255, 0]       # v9掩膜 黄（覆盖在红上）
    return rgb

axial = {}
for z in range(0, nz, 2):
    axial[z] = b64(axial_rgb(z))

json.dump({"axial": axial,
           "nz": nz, "ny": ny, "nx": nx,
           "spacing": [dx, dy, dz], "origin": list(org),
           "anchors": A}, open(os.path.join(CAL, "_axial.json"), "w"), separators=(",", ":"))
print(f"轴位 {len(axial)} 层 -> _axial.json")
print("OK")
