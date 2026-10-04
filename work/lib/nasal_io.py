# -*- coding: utf-8 -*-
"""
DICOM 读取与切片渲染 —— 自动化链路地基
不依赖 Slicer，纯 pydicom + numpy，保证可复现
"""
import os
import numpy as np
import pydicom
from PIL import Image


def load_dicom_series(dcm_dir, verbose=True):
    """读取 DICOM 序列，返回 (volume_zyx int16, spacing_xyz, origin_xyz, meta)"""
    files = [os.path.join(dcm_dir, f) for f in os.listdir(dcm_dir)
             if f.lower().endswith(".dcm")]
    if not files:
        raise FileNotFoundError(f"目录无 .dcm 文件: {dcm_dir}")

    slices = []
    for f in files:
        ds = pydicom.dcmread(f, force=True)
        slices.append(ds)

    # 按 InstanceNumber 或 ImagePositionPatient[2] 排序
    def sort_key(ds):
        if hasattr(ds, "InstanceNumber"):
            try:
                return int(ds.InstanceNumber)
            except Exception:
                pass
        return float(getattr(ds, "ImagePositionPatient", [0, 0, 0])[2])

    slices.sort(key=sort_key)

    # 构建体素阵列
    first = slices[0]
    rows = int(first.Rows)
    cols = int(first.Columns)
    n = len(slices)

    vol = np.zeros((n, rows, cols), dtype=np.int16)
    for i, ds in enumerate(slices):
        px = ds.pixel_array.astype(np.float32)
        slope = float(getattr(ds, "RescaleSlope", 1.0))
        inter = float(getattr(ds, "RescaleIntercept", 0.0))
        vol[i] = np.clip(px * slope + inter, -32768, 32767).astype(np.int16)

    # 物理间距
    ps = [float(x) for x in getattr(first, "PixelSpacing", [1.0, 1.0])]  # [row, col] = [y, x]
    if n > 1:
        p0 = np.array([float(x) for x in slices[0].ImagePositionPatient])
        p1 = np.array([float(x) for x in slices[-1].ImagePositionPatient])
        dz = float(np.linalg.norm(p1 - p0) / (n - 1))
    else:
        dz = float(getattr(first, "SliceThickness", 1.0))

    spacing_xyz = (ps[1], ps[0], dz)      # (x, y, z)
    origin_xyz = tuple(float(x) for x in getattr(first, "ImagePositionPatient", (0, 0, 0)))

    meta = {
        "n_slices": n,
        "rows": rows, "cols": cols,
        "spacing_xyz": spacing_xyz,
        "origin_xyz": origin_xyz,
        "hu_range": (int(vol.min()), int(vol.max())),
        "series_description": str(getattr(first, "SeriesDescription", "")),
        "modality": str(getattr(first, "Modality", "")),
        "slice_thickness": float(getattr(first, "SliceThickness", 0)),
        "kvp": str(getattr(first, "KVP", "")),
        "convolution_kernel": str(getattr(first, "ConvolutionKernel", "")),
        "window_center": str(getattr(first, "WindowCenter", "")),
        "window_width": str(getattr(first, "WindowWidth", "")),
        "patient_id": str(getattr(first, "PatientID", ""))[:20],
        "study_date": str(getattr(first, "StudyDate", "")),
    }
    if verbose:
        print(f"[load] {dcm_dir}")
        print(f"       体积 {vol.shape} (z,y,x)  间距 {spacing_xyz}")
        print(f"       HU {meta['hu_range']}  层厚 {meta['slice_thickness']}mm  "
              f"序列={meta['series_description']}")
    return vol, spacing_xyz, origin_xyz, meta


def window_ct(slice2d, center=800, width=2000):
    """CT 窗宽窗位 → uint8 可显示图"""
    lo = center - width / 2
    hi = center + width / 2
    img = np.clip((slice2d.astype(np.float32) - lo) / (hi - lo), 0, 1)
    return (img * 255).astype(np.uint8)


def render_views(vol, spacing_xyz, out_prefix, z_fracs=(0.35, 0.5, 0.65),
                 center=800, width=2000, crop_margin=0.15):
    """渲染轴位/冠状位/矢状位切片网格，存 PNG"""
    nz, ny, nx = vol.shape
    imgs = []

    # --- 轴位（沿 z 切） ---
    for frac in z_fracs:
        z = int(nz * frac)
        sl = vol[z]
        u8 = window_ct(sl, center, width)
        fn = f"{out_prefix}_axial_z{z:04d}.png"
        Image.fromarray(u8).save(fn)
        imgs.append((f"axial z={z}", fn, sl))

    # --- 冠状位（沿 y 切，取中间几张） ---
    for frac in (0.4, 0.5, 0.6):
        y = int(ny * frac)
        sl = vol[:, y, :]
        u8 = window_ct(sl, center, width)
        fn = f"{out_prefix}_coronal_y{y:04d}.png"
        Image.fromarray(u8).save(fn)
        imgs.append((f"coronal y={y}", fn, sl))

    # --- 矢状位（沿 x 切） ---
    for frac in (0.4, 0.5, 0.6):
        x = int(nx * frac)
        sl = vol[:, :, x]
        u8 = window_ct(sl, center, width)
        fn = f"{out_prefix}_sagittal_x{x:04d}.png"
        Image.fromarray(u8).save(fn)
        imgs.append((f"sagittal x={x}", fn, sl))

    return imgs


if __name__ == "__main__":
    import sys
    dcm_dir = sys.argv[1] if len(sys.argv) > 1 else r"D:\项目\鼻腔建模\work\00_dicom\bone"
    outdir = sys.argv[2] if len(sys.argv) > 2 else r"D:\项目\鼻腔建模\work\01_inspect"
    os.makedirs(outdir, exist_ok=True)

    vol, sp, org, meta = load_dicom_series(dcm_dir)
    print("\n=== 元数据 ===")
    for k, v in meta.items():
        print(f"  {k:22s} {v}")

    prefix = os.path.join(outdir, "ct")
    imgs = render_views(vol, sp, prefix)
    print(f"\n=== 渲染 {len(imgs)} 张切片 ===")
    for name, fn, _ in imgs:
        print(f"  {name:18s} -> {os.path.basename(fn)}  ({os.path.getsize(fn)} bytes)")
