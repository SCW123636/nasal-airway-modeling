# -*- coding: utf-8 -*-
"""
鼻腔气道自动分割 v7 — 3D 连通域 + 3D 形态判据
=================================================
思路转变（放弃脆弱的逐层追踪）：
  1. 全 3D 连通域分解
  2. 对每团空气计算稳定的 3D 形态特征：
     - 体积 volume
     - 外接盒 bbox 及其长宽高比
     - **细长度**：volume / bbox_volume （管状结构比值低）
     - **主轴比**：最大主成分长度 / 次主成分长度（管状 >> 1）
     - **质心位置**：是否靠近中线
  3. 用"管状 + 中央"判据选出鼻腔

这个方法的优势：3D 形态特征对单层噪声不敏感。
"""
import os, sys, json
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series


def region_features(mask3d, spacing):
    """计算一团 3D 区域的形态特征"""
    zz, yy, xx = np.where(mask3d)
    n = len(zz)
    if n == 0:
        return None

    # 物理坐标（用于正确计算各向尺寸）
    sx, sy, sz = spacing
    pts = np.stack([xx * sx, yy * sy, zz * sz], axis=1)   # (n, 3) 物理 mm

    f = {"volume_voxels": n}

    # bbox（体素索引）
    z0, z1 = int(zz.min()), int(zz.max())
    y0, y1 = int(yy.min()), int(yy.max())
    x0, x1 = int(xx.min()), int(xx.max())
    f["bbox"] = {"z": [z0, z1], "y": [y0, y1], "x": [x0, x1]}

    # 物理尺寸
    f["size_mm"] = {
        "z": round((z1 - z0 + 1) * sz, 2),
        "y": round((y1 - y0 + 1) * sy, 2),
        "x": round((x1 - x0 + 1) * sx, 2),
    }

    # bbox 填充率
    bbox_vol = (z1 - z0 + 1) * (y1 - y0 + 1) * (x1 - x0 + 1)
    f["fill_ratio"] = round(n / bbox_vol, 4)

    # 质心（物理）
    centroid = pts.mean(axis=0)
    f["centroid_mm"] = [round(float(c), 2) for c in centroid]

    # PCA 主轴分析
    centered = pts - centroid
    cov = np.cov(centered.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    eigvals = np.sort(eigvals)[::-1]      # 降序
    eigvals = np.maximum(eigvals, 1e-9)
    # 等效标准差（mm）
    std = np.sqrt(eigvals)
    f["pca_std_mm"] = [round(float(s), 2) for s in std]
    f["pca_ratio_1_2"] = round(float(std[0] / std[1]), 2)   # 主轴/次轴
    f["pca_ratio_2_3"] = round(float(std[1] / std[2]), 2)
    # 主轴方向（是否沿 z 轴 = 上下走向）
    main_axis = eigvecs[:, 0]
    f["main_axis"] = [round(float(v), 3) for v in main_axis]
    # 与 z 轴的夹角（度）
    ang_z = np.degrees(np.arccos(np.clip(abs(main_axis[2]), 0, 1)))
    f["angle_to_z_deg"] = round(float(ang_z), 1)

    return f


def segment_nasal_v7(vol, spacing, cfg=None, verbose=True):
    nz, ny, nx = vol.shape
    XC_mm = (nx // 2) * spacing[0]     # 中线的物理 x 坐标
    C = {
        "hu_air_max": -300,
        "min_volume": 20000,          # 最小体积过滤
        "noise_remove": True,
    }
    if cfg:
        C.update(cfg)

    air = vol < C["hu_air_max"]

    # 轻量去噪
    if C["noise_remove"]:
        air = ndimage.binary_opening(air, structure=np.ones((2, 2, 2)))

    # 全 3D 连通域
    lbl, n = ndimage.label(air, structure=np.ones((3, 3, 3)))
    if verbose:
        print(f"=== v7 诊断 ===")
        print(f"3D 连通域总数: {n}")

    sizes = ndimage.sum(air, lbl, range(1, n + 1))
    order = np.argsort(-sizes)

    # 分析前 30 大
    feats = []
    for idx in order[:30]:
        lab = int(idx) + 1
        m = lbl == lab
        if m.sum() < C["min_volume"]:
            continue
        f = region_features(m, spacing)
        f["label"] = lab
        feats.append(f)

    if verbose:
        print(f"\n{'lab':>6} {'体积':>10} {'fill':>7} {'主轴/次':>8} {'std(mm)':>22} "
              f"{'尺寸mm(z,y,x)':>22} {'倾角z':>6} {'质心x(mm)':>10}")
        for f in feats[:15]:
            print(f"{f['label']:>6} {f['volume_voxels']:>10,} {f['fill_ratio']:>7.3f} "
                  f"{f['pca_ratio_1_2']:>8.2f} {str(f['pca_std_mm']):>22} "
                  f"{str([f['size_mm']['z'],f['size_mm']['y'],f['size_mm']['x']]):>22} "
                  f"{f['angle_to_z_deg']:>6.1f} {f['centroid_mm'][0]:>10.1f}")

    return {"feats": feats, "air": air, "labels": lbl, "n": n}


if __name__ == "__main__":
    vol, sp, org, meta = load_dicom_series(
        r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
    print(f"体积 {vol.shape} 间距 {sp}")
    print(f"中线 x = {(vol.shape[2]//2)*sp[0]:.2f} mm\n")

    res = segment_nasal_v7(vol, sp)

    outdir = r"D:\项目\鼻腔建模\work\02_segment"
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "v7_features.json"), "w", encoding="utf-8") as f:
        json.dump(res["feats"], f, ensure_ascii=False, indent=2)
    print(f"\n特征已保存 -> v7_features.json")
