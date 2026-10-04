# -*- coding: utf-8 -*-
"""多患者鼻腔质量检查 —— 用途已收窄（2026-10-01 裁定）

保留用途（仅这两类）：
  1. 体外 / 体内空气分离（与轴位图像四边连通者判为体外）—— 方法已成立，跨例可用。
  2. 质量检查：HU 纯净度（空气域内 HU>0 体素，验收要求 =0）+ 对称比 / 跨度（仅作提示）。

已停用（不再作为判据）：
  - 面积导数定鼻孔入口：三例交叉验证全失败，锚点落在口腔/上颌窦，故默认不执行
    （由 AREA_DERIVATIVE_NOSE_ANCHOR 开关控制，默认 False）。
  - 对称比≥0.7、bbox 跨度 50–70 mm、面积导数拐点：仅作提示，不再判定鼻腔正确性。

注意：本脚本只做「体外/体内分离 + 质检」，不再产出分割结果；分割见 work/分割流程规范.md。
用法：PythonSlicer.exe calib_multi.py
"""
# 面积导数定鼻孔（已证伪，默认关闭）：仅作可选对照
AREA_DERIVATIVE_NOSE_ANCHOR = False

import os, sys, json, csv, traceback
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dicom_sitk import load_series_sitk as load_dicom_series
from nasal_io import window_ct

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from PIL import Image

ROOT = r"D:\项目\鼻腔建模"
CLEAN = os.path.join(ROOT, "资料", "脱敏数据_clean")
OUT = os.path.join(ROOT, "work", "03_calib", "multi")
os.makedirs(OUT, exist_ok=True)

for cand in ["Microsoft YaHei", "SimHei", "DejaVu Sans"]:
    if any(cand.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [cand]
        break
plt.rcParams["axes.unicode_minus"] = False

# ---- 每个患者选定的"最佳骨窗"序列（相对 CLEAN 的路径）----
# 选择依据：骨窗 kernel（SHARP/VSHARP）+ 最小层厚
CASES = [
    ("患者1", r"患者1\______-______\20260127\202-1.0 x 0.8 Bone"),
    ("患者2", r"患者2\p01360058-____\20250902-Head^07_Sinus (Adult)\4-Sinus  0.75  H40s"),
    ("患者3", r"患者3\250111559-TKT\20260217-5.___\202-0.6 x 0.6_BONE"),
]


def smooth(a, k=9):
    if len(a) < k:
        return a.copy()
    return np.convolve(a, np.ones(k) / k, mode="same")


def calib_one(vol, sp, org, name):
    """核心标定：体内空气(排除边缘连通) + 面积导数拐点"""
    nz, ny, nx = vol.shape
    dx, dy, dz = sp
    air = vol < -300

    # --- 体外空气 = 与轴位图像四边连通的空气 ---
    outside = np.zeros_like(air)
    for z in range(nz):
        a = air[z]
        if not a.any():
            continue
        lbl, n = ndimage.label(a, structure=np.ones((3, 3)))
        if n == 0:
            continue
        edge_labels = set(lbl[0, :]) | set(lbl[-1, :]) | set(lbl[:, 0]) | set(lbl[:, -1])
        edge_labels.discard(0)
        if edge_labels:
            outside[z] = np.isin(lbl, list(edge_labels))
    inside = air & (~outside)

    # --- 逐层统计 ---
    rows = []
    for z in range(nz):
        m = inside[z]
        n = int(m.sum())
        if n == 0:
            rows.append({"z": z, "n": 0, "x_min": -1, "x_max": -1, "x_span": 0,
                         "cx": -1.0, "ncomp": 0})
            continue
        ys, xs = np.where(m)
        lbl, nc = ndimage.label(m, structure=np.ones((3, 3)))
        rows.append({"z": z, "n": n, "x_min": int(xs.min()), "x_max": int(xs.max()),
                     "x_span": int(xs.max() - xs.min() + 1),
                     "cx": round(float(xs.mean()), 2), "ncomp": int(nc)})

    prof = np.array([r["n"] for r in rows], dtype=float)
    cx = np.array([r["cx"] for r in rows], dtype=float)
    span = np.array([r["x_span"] for r in rows], dtype=float)
    ps = smooth(prof, 9)
    dps = np.gradient(ps)

    nz_any = np.where(prof > 0)[0]
    if len(nz_any) == 0:
        return None, None, None
    z_lo, z_hi = int(nz_any.min()), int(nz_any.max())

    # --- 面积导数定鼻孔（已证伪，默认停用，见文件头 AREA_DERIVATIVE_NOSE_ANCHOR）---
    if AREA_DERIVATIVE_NOSE_ANCHOR:
        search_from = z_lo + 15
        if search_from >= nz - 2:
            search_from = z_lo + 2
        i_rise = search_from + int(np.argmax(dps[search_from:]))
        i = i_rise
        while i > search_from and dps[i] > 0:
            i -= 1
        z_nostril = i
        z_peak = int(z_nostril + np.argmax(ps[z_nostril:]))
        i_fall = z_peak + int(np.argmin(dps[z_peak:]))
        z_widest = int(z_nostril + np.argmax(span[z_nostril:z_peak + 1]))
    else:
        # 降级：不再锚定解剖位置；HU 质检与提示性统计覆盖整体体内空气域 [z_lo, z_hi]
        z_nostril, z_peak = z_lo, (z_lo + z_hi) // 2
        i_fall, z_widest = z_hi, (z_lo + z_hi) // 2

    # --- 质量闸门 ---
    # 对称比：以鼻腔段质心的 x 为中心，左右体素量之比
    nasal_mask = np.zeros_like(inside)
    nasal_mask[z_nostril:i_fall + 1] = inside[z_nostril:i_fall + 1]
    if nasal_mask.any():
        zz_, yy_, xs_ = np.where(nasal_mask)   # 3D 掩膜 → 三个索引数组
        x_c = float(np.median(xs_))
        left = int((xs_ < x_c).sum())
        right = int((xs_ > x_c).sum())
        sym = round(min(left, right) / max(left, right), 3) if max(left, right) else 0.0
    else:
        sym, left, right, x_c = 0.0, 0, 0, 0

    # HU 纯净度：鼻腔段掩膜里 HU>0 的比例（应 = 0）
    hu_impure = 0
    if nasal_mask.any():
        vals = vol[nasal_mask]
        hu_impure = int((vals > 0).sum())
    allvox = int(nasal_mask.sum())

    lm = {
        "patient": name,
        "shape": list(vol.shape),
        "spacing_xyz_mm": [round(float(v), 6) for v in sp],
        "origin_ipp": [round(float(v), 4) for v in org],
        "slice_thickness_mm": round(float(dz), 4),
        "z_nostril_entry": {"z": int(z_nostril), "mm_z": round(float(org[2] + z_nostril * dz), 3)},
        "z_nasal_peak": {"z": int(z_peak), "mm_z": round(float(org[2] + z_peak * dz), 3)},
        "z_nasopharynx": {"z": int(i_fall), "mm_z": round(float(org[2] + i_fall * dz), 3)},
        "z_widest": {"z": int(z_widest), "mm_z": round(float(org[2] + z_widest * dz), 3)},
        "nasal_span_mm": round(float((i_fall - z_nostril) * dz), 2),
        "nasal_span_slices": int(i_fall - z_nostril),
        "x_center": round(float(x_c), 1),
        "air_inside_voxels": int(inside.sum()),
        "air_outside_voxels": int(outside.sum()),
        "gate_symmetry_ratio": sym,
        "gate_sym_left": left, "gate_sym_right": right,
        "gate_hu_impure_voxels": hu_impure,
        "gate_hu_impure_frac": round(hu_impure / allvox, 6) if allvox else None,
        "nasal_mask_voxels": allvox,
    }
    diag = {"prof": prof, "ps": ps, "dps": dps, "span": span, "cx": cx,
            "rows": rows, "inside": inside, "outside": outside,
            "z_lo": z_lo, "z_hi": z_hi, "nz": nz, "dz": dz, "org": org}
    return lm, diag, vol


results = []
all_failed = []
for name, rel in CASES:
    d = os.path.join(CLEAN, rel)
    entry = {"patient": name, "path": rel}
    try:
        if not os.path.isdir(d):
            entry["status"] = "DIR_NOT_FOUND"
            results.append(entry)
            continue
        vol, sp, org, meta = load_dicom_series(d, verbose=False)
        entry["series_desc"] = meta["series_description"]
        entry["kernel"] = meta["convolution_kernel"]
        entry["n_slices"] = meta["n_slices"]
        entry["hu_range"] = list(meta["hu_range"])

        lm, diag, _ = calib_one(vol, sp, org, name)
        if lm is None:
            entry["status"] = "NO_AIR_FOUND"
            results.append(entry)
            continue
        entry["status"] = "OK"
        entry.update(lm)

        # --- 每例出剖面图 ---
        fig, axes = plt.subplots(3, 1, figsize=(13, 10), dpi=100, sharex=True)
        nz = diag["nz"]
        axes[0].plot(np.arange(nz), diag["prof"], lw=1.0, color="#1f77b4", label="体内空气体素/层")
        axes[0].plot(np.arange(nz), diag["ps"], lw=1.6, color="#ff7f0e", alpha=0.85, label="平滑")
        axb = axes[0].twinx()
        axb.plot(np.arange(nz), diag["dps"], lw=0.9, color="#999999", alpha=0.7, label="导数")
        axb.axhline(0, color="#cccccc", lw=0.6)
        _anchor_labels = (
            [(lm["z_nostril_entry"]["z"], "鼻孔入口", "#2ca02c"),
             (lm["z_nasal_peak"]["z"], "鼻腔峰值", "#d62728"),
             (lm["z_nasopharynx"]["z"], "鼻咽过渡", "#9467bd")]
            if AREA_DERIVATIVE_NOSE_ANCHOR else
            [(lm["z_nostril_entry"]["z"], "体内空气下界", "#2ca02c"),
             (lm["z_nasal_peak"]["z"], "体内空气中界", "#d62728"),
             (lm["z_nasopharynx"]["z"], "体内空气上界", "#9467bd")]
        )
        for z, lab, c in _anchor_labels:
            axes[0].axvline(z, ls="--", lw=1.3, color=c)
            axes[0].annotate(f"{lab}\nz={z}", xy=(z, diag["ps"][z]), xytext=(10, 14),
                             textcoords="offset points", fontsize=9, color=c,
                             arrowprops=dict(arrowstyle="->", color=c, lw=0.9))
        axes[0].set_ylabel("体内空气体素/层")
        axes[0].set_title(f"{name}  {meta['series_description']}  "
                          f"({meta['spacing_xyz'][2]:.3f}mm 层厚, kernel={meta['convolution_kernel']})\n"
                          f"鼻腔跨度 = {lm['nasal_span_mm']} mm")
        axes[0].legend(fontsize=9, loc="upper left")
        axes[0].grid(alpha=0.3)
        axes[1].plot(np.arange(nz), diag["span"], lw=1.2, color="#2ca02c")
        axes[1].axvline(lm["z_widest"]["z"], ls="--", lw=1.3, color="#8c564b")
        axes[1].set_ylabel("x 跨度 (体素)")
        axes[1].grid(alpha=0.3)
        v = diag["prof"] > 0
        axes[2].plot(np.arange(nz)[v], diag["cx"][v], lw=1.2, color="#d62728")
        axes[2].set_xlabel("z 层索引")
        axes[2].set_ylabel("质心 x")
        axes[2].grid(alpha=0.3)
        for a in axes:
            a.set_xlim(max(0, diag["z_lo"] - 15), min(nz, diag["z_hi"] + 15))
        fig.tight_layout()
        fig.savefig(os.path.join(OUT, f"profile_{name}.png"))
        plt.close(fig)

        # --- 体内/体外对比图 ---
        zs = sorted(set([max(0, lm["z_nostril_entry"]["z"] - 20), lm["z_nostril_entry"]["z"],
                         lm["z_nasal_peak"]["z"], lm["z_nasopharynx"]["z"],
                         min(nz - 1, lm["z_nasopharynx"]["z"] + 20)]))
        zs = [z for z in zs if 0 <= z < nz]
        tiles = []
        for z in zs:
            u8 = window_ct(vol[z], 800, 2000)
            rgb = np.stack([u8] * 3, axis=-1).copy()
            rgb[diag["outside"][z]] = [90, 140, 255]
            rgb[diag["inside"][z]] = [255, 90, 90]
            tiles.append(rgb)
        h, w = tiles[0].shape[:2]
        sc = 0.5
        h2, w2 = int(h * sc), int(w * sc)
        cols = len(tiles)
        canvas = np.zeros((h2, cols * w2, 3), dtype=np.uint8)
        for i, t in enumerate(tiles):
            canvas[:, i * w2:(i + 1) * w2] = np.array(
                Image.fromarray(t).resize((w2, h2)))
        Image.fromarray(canvas).save(os.path.join(OUT, f"inout_{name}.png"))

        results.append(entry)
    except Exception as e:
        entry["status"] = "ERROR"
        entry["err"] = repr(e)
        entry["tb"] = traceback.format_exc()[-600:]
        results.append(entry)
        all_failed.append((name, repr(e)))

with open(os.path.join(OUT, "multi_calib.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("\n===== 多患者标定核验 =====")
print(f"{'患者':6s} {'序列':22s} {'层厚':>7s} {'层数':>5s} {'跨度mm':>8s} {'对称比':>7s} {'HU杂':>6s} {'状态'}")
for r in results:
    if r.get("status") != "OK":
        print(f"{r['patient']:6s} {'-':22s} {'-':>7s} {'-':>5s} {'-':>8s} {'-':>7s} {'-':>6s} {r.get('status')}")
        continue
    print(f"{r['patient']:6s} {r['series_desc'][:22]:22s} {r['slice_thickness_mm']:7.3f} "
          f"{r['n_slices']:5d} {r['nasal_span_mm']:8.2f} {r['gate_symmetry_ratio']:7.3f} "
          f"{r['gate_hu_impure_voxels']:6d} OK")
print("\n输出目录:", OUT)
if all_failed:
    print("失败:", all_failed)
