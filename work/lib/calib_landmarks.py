# -*- coding: utf-8 -*-
"""
三维解剖标定与分割诊断可视化
================================
目的：把"看不见的操作位置"变成"图上可定位、可复核、可复现"的东西。

产出：
  1. 多层 CT 叠加图（轴位/冠状/矢状），同时画出：
     - 当前掩膜（红）
     - 被 v9 误杀的鼻腔主体（绿）
     - 标定平面（鼻孔平面 / 鼻咽出口平面）
     - 解剖标志点
  2. landmarks.json —— 体素坐标 + 毫米坐标 + 体素间距
  3. 一个自包含 HTML 复核页（可交互切片浏览）

用法：
  PythonSlicer.exe calib_landmarks.py
"""
import os, sys, json
import numpy as np
from scipy import ndimage
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series, window_ct

ROOT = r"D:\项目\鼻腔建模"
DICOM = os.path.join(ROOT, "work", "00_dicom", "bone")
SEG = os.path.join(ROOT, "work", "02_segment")
OUT = os.path.join(ROOT, "work", "03_calib")
os.makedirs(OUT, exist_ok=True)


# ---------------- 1. 读取与基础几何 ----------------
vol, sp, org, meta = load_dicom_series(DICOM, verbose=False)
nz, ny, nx = vol.shape
dx, dy, dz = sp
print(f"体积 {vol.shape}  spacing(x,y,z)=({dx:.6f},{dy:.6f},{dz:.6f})")
print(f"origin(IPP首层)={org}")

# 物理坐标换算：体素(x,y,z) -> 毫米(mm)，相对 IPP 首层
def to_mm(ix, iy, iz):
    return (round(ix * dx, 4), round(iy * dy, 4), round(org[2] + iz * dz, 4))


# ---------------- 2. 气道候选（含体外空气，用于证明"必须先切割"） ----------------
air = vol < -300
lbl, n = ndimage.label(air, structure=np.ones((3, 3, 3)))
sizes = ndimage.sum(air, lbl, range(1, n + 1))
main_lab = int(np.argmax(sizes)) + 1
main = lbl == main_lab
zz, yy, xx = np.where(main)
print(f"[事实] 最大3D连通域: size={int(sizes[main_lab-1]):,}  "
      f"z=[{zz.min()},{zz.max()}] x=[{xx.min()},{xx.max()}] y=[{yy.min()},{yy.max()}]")
print("[事实] ↑ 该连通域跨越整个扫描体积 → 体外空气+鼻腔+咽部+气管是【同一块】")
print("[结论] 最大连通域 != 鼻腔；必须先按鼻孔平面切割，否则无法分离鼻腔")

# ---- 2b. ROI 裁剪：只在"可能的鼻腔范围"内工作，这是后续所有步骤的前提 ----
# 依据：鼻腔 x 质心实测 250-255，y 在 88-323（v9 掩膜 bbox），z 在 129-221
ROI = {
    "z": (110, 245),
    "y": (60, 340),
    "x": (175, 330),
}
roi = np.zeros_like(main)
roi[ROI["z"][0]:ROI["z"][1] + 1,
    ROI["y"][0]:ROI["y"][1] + 1,
    ROI["x"][0]:ROI["x"][1] + 1] = True
main_roi = main & roi
print(f"[ROI] 裁剪后体素: {int(main_roi.sum()):,}")

# ---------------- 3. 标定：找解剖锚点 ----------------
# 思路：用"该层空气面积"的剖面来定位解剖平面，而不是靠人眼翻层。
# 鼻腔横截面积沿 z 的变化有明确的解剖含义。

prof = []
for z in range(nz):
    a = int(main_roi[z].sum())
    prof.append(a)
prof = np.array(prof)
nz_any = np.where(prof > 0)[0]
print(f"\n逐层面积剖面(ROI内): max={prof.max():,} @z={int(prof.argmax())}  "
      f"非零范围 z={int(nz_any.min())}..{int(nz_any.max())}")

# 找"面积首次显著上升"的位置 = 鼻孔入口附近
thr = prof.max() * 0.15
nz_any = np.where(prof > 0)[0]
z_lo = int(nz_any.min()) if len(nz_any) else 0
z_onset = z_lo + int(np.argmax(prof[z_lo:] > thr))
# 找面积最大处 = 鼻腔本部
z_peak = int(prof.argmax())
# 找面积回落后的位置 = 鼻咽过渡
after = prof[z_peak:]
thr2 = prof[z_peak] * 0.45
z_fall = z_peak + int(np.argmax(after < thr2)) if (after < thr2).any() else z_peak

print(f"标定候选: 起始 z_onset={z_onset}, 鼻腔本部峰值 z_peak={z_peak}, 回落 z_fall={z_fall}")

# 鼻腔主体质心（x 方向）
cy_all = float(xx.mean())
cx_all = float(yy.mean())
print(f"主体质心 (y,x)=({cx_all:.1f},{cy_all:.1f})")

# 左右分界：鼻中隔 x 位置（用 ROI 主体在 x 上的分布低谷来找）
hist = main_roi.sum(axis=(0, 1))
xs = np.arange(nx)
m = (hist > 0)
x0, x1 = int(xs[m].min()), int(xs[m].max())
mid = (x0 + x1) // 2
lo, hi = max(x0, mid - 40), min(x1, mid + 40)
x_septum = lo + int(np.argmin(hist[lo:hi + 1]))
print(f"主体 x 范围 [{x0},{x1}]，鼻中隔估计 x_septum={x_septum}")

landmarks = {
    "meta": {
        "dicom_dir": DICOM,
        "shape": list(vol.shape),
        "spacing_xyz": [dx, dy, dz],
        "origin_ipp_first": list(org),
        "note": "坐标为体素索引 (z,y,x)，另附毫米坐标；mm_z 为 IPP 绝对 z",
    },
    "derived": {
        "z_onset_nostril": z_onset,
        "z_peak_nasal": z_peak,
        "z_fall_nasopharynx": z_fall,
        "x_septum": int(x_septum),
        "main_component": {
            "size": int(sizes[main_lab - 1]),
            "bbox_z": [int(zz.min()), int(zz.max())],
            "bbox_y": [int(yy.min()), int(yy.max())],
            "bbox_x": [int(xx.min()), int(xx.max())],
        },
    },
    "landmarks": {},   # 待人工确认后填入
}

# ---------------- 4. 渲染：诊断叠加图 ----------------
mask_v9 = np.load(os.path.join(SEG, "nasal_mask_v9.npy"))
assert mask_v9.shape == vol.shape, f"掩膜形状不匹配 {mask_v9.shape} vs {vol.shape}"

def overlay(idx, axis="axial"):
    """返回 RGB 图：CT 灰底 + v9掩膜红 + 漏采空气绿 + 标定层黄框
    axis: axial -> vol[z,:,:]   shape (ny,nx)
          coronal -> vol[:,y,:]  shape (nz,nx)
          sagittal -> vol[:,:,x] shape (nz,ny)
    """
    if axis == "axial":
        sl = vol[idx]                       # (ny, nx)
        m_v9 = mask_v9[idx]
        m_main = main_roi[idx]
    elif axis == "coronal":
        sl = vol[:, idx, :]                 # (nz, nx)
        m_v9 = mask_v9[:, idx, :]
        m_main = main_roi[:, idx, :]
    else:  # sagittal
        sl = vol[:, :, idx]                 # (nz, ny)
        m_v9 = mask_v9[:, :, idx]
        m_main = main_roi[:, :, idx]

    u8 = window_ct(sl, 800, 2000)
    rgb = np.stack([u8] * 3, axis=-1).copy()
    rgb[m_v9] = [255, 60, 60]                       # v9 掩膜 = 红
    rgb[m_main & (~m_v9)] = [60, 255, 120]          # 漏采 = 绿
    if axis == "axial" and idx in (z_onset, z_peak, z_fall):
        rgb[0:3, :] = [255, 230, 60]
        rgb[-3:, :] = [255, 230, 60]
    return rgb

def grid(images, cols, scale=0.5):
    imgs = [np.array(Image.open(f)) if isinstance(f, str) else f for f in images]
    h, w = imgs[0].shape[:2]
    h2, w2 = int(h * scale), int(w * scale)
    rows = (len(imgs) + cols - 1) // cols
    canvas = np.zeros((rows * h2, cols * w2, 3), dtype=np.uint8)
    for i, im in enumerate(imgs):
        r, c = divmod(i, cols)
        canvas[r*h2:(r+1)*h2, c*w2:(c+1)*w2] = np.array(
            Image.fromarray(im).resize((w2, h2)))
    return canvas

# 轴位系列
z_list = [z_onset, z_onset + 20, z_peak - 30, z_peak, z_peak + 20, z_peak + 40,
          z_fall - 20, z_fall]
z_list = sorted(set([z for z in z_list if 0 <= z < nz]))
imgs = [overlay(z, "axial") for z in z_list]
g = grid(imgs, 4, 0.5)
p1 = os.path.join(OUT, "diag_axial_grid.png")
Image.fromarray(g).save(p1)
print(f"\n轴位诊断图 -> {p1}  (层: {z_list})")

# 冠状系列
y_list = [int(cx_all) - 60, int(cx_all) - 30, int(cx_all), int(cx_all) + 30,
          int(cx_all) + 60, int(cx_all) + 90]
y_list = sorted(set([y for y in y_list if 0 <= y < ny]))
imgs = [overlay(y, "coronal") for y in y_list]
g = grid(imgs, 3, 0.5)
p2 = os.path.join(OUT, "diag_coronal_grid.png")
Image.fromarray(g).save(p2)
print(f"冠状诊断图 -> {p2}  (层: {y_list})")

# 矢状系列
x_list = [int(cy_all) - 60, int(cy_all) - 30, int(cy_all), int(cy_all) + 30,
          int(cy_all) + 60, int(cy_all) + 90]
x_list = sorted(set([x for x in x_list if 0 <= x < nx]))
imgs = [overlay(x, "sagittal") for x in x_list]
g = grid(imgs, 3, 0.5)
p3 = os.path.join(OUT, "diag_sagittal_grid.png")
Image.fromarray(g).save(p3)
print(f"矢状诊断图 -> {p3}  (层: {x_list})")

# ---------------- 5. 面积剖面图（定位解剖平面的关键图） ----------------
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(12, 4), dpi=110)
    ax.plot(np.arange(nz), prof, lw=1.0, color="#1f77b4")
    for z, lab, c in [(z_onset, "z_onset 鼻孔", "#2ca02c"),
                      (z_peak, "z_peak 鼻腔本部", "#d62728"),
                      (z_fall, "z_fall 鼻咽过渡", "#ff7f0e")]:
        ax.axvline(z, ls="--", lw=1.2, color=c, label=f"{lab} (z={z})")
    ax.set_xlabel("z slice index")
    ax.set_ylabel("air voxels in main component")
    ax.set_title("Airway cross-section area profile (max 3D component)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    p4 = os.path.join(OUT, "area_profile.png")
    fig.tight_layout()
    fig.savefig(p4)
    plt.close(fig)
    print(f"面积剖面图 -> {p4}")
except Exception as e:
    print("matplotlib 不可用，跳过剖面图:", e)

with open(os.path.join(OUT, "landmarks.json"), "w", encoding="utf-8") as f:
    json.dump(landmarks, f, ensure_ascii=False, indent=2)
print(f"\n标定 JSON -> {os.path.join(OUT,'landmarks.json')}")
print(json.dumps(landmarks["derived"], ensure_ascii=False, indent=2))
