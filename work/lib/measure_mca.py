# -*- coding: utf-8 -*-
"""measure_mca.py — 沿前后轴测量鼻腔最小截面积 (MCA, minimal cross-sectional area)。

原理
----
MCA 是鼻阀(nasal valve)的功能性量化量，**不是解剖标签**。
TotalSegmentator 及任何分割模型都不会标它 —— 因为它不是"画"出来的，是"量"出来的：
沿鼻腔流道从鼻孔往后扫，垂直于前后轴的空气截面积的最小值。

本脚本用体素计数法：

    A(s) = N(s) * V_voxel / ds

其中 s 为沿前后轴(posterior)距同侧鼻孔的距离，N(s) 为该 slab 内的空气体素数，
V_voxel 为单个体素体积，ds 为 slab 厚度。体积/厚度 = 平均截面积，这是 AR(声反射鼻
测量)面积-距离曲线的 CT 等价物，两者文献上可互校。

产出
----
每侧输出：MCA 值(mm²/cm²)、MCA 距鼻孔距离、面积-距离曲线、气道不连续告警。
与文献参考值做**量级**对账（不是合格线，见 LITERATURE）。

诚实性约束
----------
- 输入几何为 provisional(未经人工复核)时，输出 status 一律标 `provisional_geometry`。
- 文献参考值只作量级哨兵：AR 与 CT 在体位(坐位/卧位)、黏膜状态(是否减充血)、
  起点定义上均不同，两者系统性有偏，不得当作合格线。
- 曲线中出现空 slab(气道断层)时如实报出，不插值抹平、不静默跳过。
- 产物携带生成参数与输入 SHA-256，保证可追溯。

用法
----
python measure_mca.py --case p0
python measure_mca.py --case p3 --bin-mm 0.5 --anterior-window-mm 40
"""

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone

import numpy as np
import SimpleITK as sitk

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 复用已验证的坐标工具，避免自己重算仿射矩阵出错
from auto_anatomy_landmarks import affine as sitk_affine  # noqa: E402
from auto_anatomy_landmarks import physical               # noqa: E402

DEFAULT_BIN_MM = 0.35
DEFAULT_ANTERIOR_WINDOW_MM = 40.0

# ---------------------------------------------------------------- 文献参考值
LITERATURE = {
    "source": "acoustic rhinometry (AR) 文献综述值；AR 与 CT 面积测量相关性已被文献确认可互校",
    "role": "量级哨兵，不是合格线 —— AR 与 CT 在体位/黏膜状态/起点定义上系统性有偏",
    "asian_adult_mca_cm2": 0.75,
    "asian_adult_sd_cm2": 0.03,
    "other_populations_cm2": {
        "caucasian": 0.72,
        "oriental": 0.62,
        "african_american": 0.88,
        "american_indian": 0.70,
    },
    "healthy_51_cavities_mca_cm2": 0.62,
    "healthy_51_distance_from_nostril_cm": 2.35,
    "septal_deviation_threshold_cm2": 0.28,
    "reported_range_cm2": [0.3, 1.5],
}


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# ITK/SimpleITK 在 Windows 上无法打开含非 ASCII 的路径（本项目已知坑，读和写都会失败）。
# 因此先把输入复制到纯 ASCII 缓存目录再读。
ASCII_CACHE = os.path.join("C:\\", "ts_work", "_mca_cache")


def _ascii_copy(path):
    """路径含非 ASCII 时复制到 ASCII 缓存，返回可读路径。"""
    try:
        path.encode("ascii")
        return path
    except UnicodeEncodeError:
        os.makedirs(ASCII_CACHE, exist_ok=True)
        h = hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
        dst = os.path.join(ASCII_CACHE, h + ".nii.gz")
        if not os.path.exists(dst):
            shutil.copyfile(path, dst)
        return dst


def read_bool(path):
    img = sitk.ReadImage(_ascii_copy(path))
    arr = sitk.GetArrayFromImage(img)  # zyx
    return arr > 0, img


def area_distance_curve(mask, a, nostril_pt, posterior, bin_mm, window_mm):
    """体素计数法算面积-距离曲线。

    返回 (distance_mm, area_mm2, discontinuity_mask)。
    distance 为该 slab 中心距鼻孔的距离；area 为平均截面积 mm²。
    """
    idx = np.argwhere(mask)                    # (N, 3) zyx
    if idx.size == 0:
        return np.empty(0), np.empty(0), np.empty(0, dtype=bool)

    pts = physical(idx, a)                     # (N, 3) xyz LPS mm
    s = (pts - np.asarray(nostril_pt, float)) @ np.asarray(posterior, float)

    n_bin = int(np.ceil(window_mm / bin_mm))
    bins = np.floor(s / bin_mm).astype(int)
    keep = (bins >= 0) & (bins < n_bin)
    bins = bins[keep]
    if bins.size == 0:
        return np.empty(0), np.empty(0), np.empty(0, dtype=bool)

    counts = np.bincount(bins, minlength=n_bin).astype(float)
    v_vox = abs(float(np.linalg.det(a[:3, :3])))
    area = counts * v_vox / bin_mm
    dist = (np.arange(n_bin) + 0.5) * bin_mm

    # 气道断层：有体素的区间内部出现空 slab
    occupied = np.nonzero(counts > 0)[0]
    disc = np.zeros(n_bin, dtype=bool)
    if occupied.size:
        lo, hi = occupied.min(), occupied.max()
        inside = np.arange(lo, hi + 1)
        disc[inside[counts[inside] <= 0]] = True

    return dist, area, disc


def side_report(name, mask, a, nostril_pt, posterior, bin_mm, window_mm, entry_skip_mm):
    dist, area, disc = area_distance_curve(
        mask, a, nostril_pt, posterior, bin_mm, window_mm
    )
    out = {
        "side": name,
        "voxels": int(mask.sum()),
        "volume_ml": float(mask.sum() * abs(np.linalg.det(a[:3, :3])) / 1000.0),
        "n_slabs": int(dist.size),
        "discontinuity_slabs": int(disc.sum()),
        "entry_skip_mm": entry_skip_mm,
    }
    if dist.size == 0:
        out.update({"mca_mm2": None, "status": "no_voxels_in_window"})
        return out, (dist, area, disc)

    occ = area > 0
    if not occ.any():
        out.update({"mca_mm2": None, "status": "no_voxels_in_window"})
        return out, (dist, area, disc)

    a_occ, d_occ = area[occ], dist[occ]

    def _min(sub_a, sub_d, tag):
        if sub_a.size == 0:
            return {f"mca_{tag}_mm2": None}
        k = int(np.argmin(sub_a))
        return {
            f"mca_{tag}_mm2": round(float(sub_a[k]), 3),
            f"mca_{tag}_cm2": round(float(sub_a[k]) / 100.0, 4),
            f"mca_{tag}_distance_mm": round(float(sub_d[k]), 2),
        }

    out.update(_min(a_occ, d_occ, "incl_entry"))
    post = d_occ >= entry_skip_mm
    out.update(_min(a_occ[post], d_occ[post], "post_entry"))

    # 最小值若落在入口过渡段，极可能是入口斜切造成的边界伪影，不是鼻阀
    m_all = out.get("mca_incl_entry_distance_mm")
    m_post = out.get("mca_post_entry_distance_mm")
    out["entry_boundary_artifact_suspected"] = bool(
        m_all is not None and m_all < entry_skip_mm
    )
    out["dominant_minimum_is_post_entry"] = bool(
        m_post is not None and m_all is not None
        and abs(m_post - m_all) > 1e-9
    )
    out.update({
        "mean_area_mm2": round(float(a_occ.mean()), 3),
        "max_area_mm2": round(float(a_occ.max()), 3),
        "window_mm": window_mm,
    })

    ref = LITERATURE["asian_adult_mca_cm2"]
    primary = out.get("mca_post_entry_cm2") or out.get("mca_incl_entry_cm2")
    if primary:
        out["primary_mca_cm2"] = primary
        out["ratio_to_asian_reference"] = round(primary / ref, 3)
        out["magnitude_check"] = (
            "same_order_of_magnitude" if 0.4 <= primary / ref <= 2.5
            else "out_of_expected_range_investigate_geometry"
        )
    out["status"] = "computed"
    return out, (dist, area, disc)


def main():
    ap = argparse.ArgumentParser(description="测量鼻腔最小截面积 MCA")
    ap.add_argument("--case", required=True, help="病例键，如 p0 / p1 / p2 / p3 / p3t1")
    ap.add_argument("--mask", default=None, help="候选气道掩膜 nii.gz")
    ap.add_argument("--landmarks", default=None, help="landmarks.json")
    ap.add_argument("--labels-dir", default=None, help="TS 标签目录(含 nasal_cavity_left/right)")
    ap.add_argument("--ct", default=None, help="源 CT，用于记录 SHA-256")
    ap.add_argument("--out-dir", default=None, help="输出目录")
    ap.add_argument("--bin-mm", type=float, default=DEFAULT_BIN_MM)
    ap.add_argument("--anterior-window-mm", type=float, default=DEFAULT_ANTERIOR_WINDOW_MM)
    ap.add_argument("--entry-skip-mm", type=float, default=3.0,
                    help="入口过渡段宽度；最小值落在此段内即标记为疑似入口斜切伪影")
    args = ap.parse_args()

    case = args.case
    work = r"D:\项目\鼻腔建模\work"
    mask_p = args.mask or os.path.join(
        work, "05_ts_seg", case, "anatomy", "main_nasal_airway_T300_provisional.nii.gz")
    lm_p = args.landmarks or os.path.join(work, "06_auto_landmarks", case, "landmarks.json")
    lab_d = args.labels_dir or os.path.join("C:\\", "ts_work", case, "masks")
    ct_p = args.ct or os.path.join("C:\\", "ts_work", case, "ct.nii.gz")
    out_d = args.out_dir or os.path.join(work, "05_ts_seg", case, "anatomy")

    for p in (mask_p, lm_p):
        if not os.path.exists(p):
            sys.exit(f"missing input: {p}")

    os.makedirs(out_d, exist_ok=True)

    cand, cand_img = read_bool(mask_p)
    a = sitk_affine(cand_img)

    with open(lm_p, encoding="utf-8") as f:
        lm = json.load(f)
    frame = lm["anatomy_frame"]
    posterior = np.asarray(frame["posterior_lps"], float)
    posterior = posterior / np.linalg.norm(posterior)

    nostril_L = lm["landmarks"]["nostril_L"]["point_lps_mm"]
    nostril_R = lm["landmarks"]["nostril_R"]["point_lps_mm"]
    # 左右用 TS 语义标签分离，不用几何中缝（几何中缝已被三例交叉验证证伪）
    sides = {}
    for name, key in (("left", "nasal_cavity_left"), ("right", "nasal_cavity_right")):
        lp = os.path.join(lab_d, key + ".nii.gz")
        if os.path.exists(lp):
            lab, _ = read_bool(lp)
            if lab.shape == cand.shape:
                sides[name] = cand & lab
            else:
                sys.exit(f"geometry mismatch: {lp}")
        else:
            sys.exit(f"missing label: {lp}")

    reports = {}
    curves = {}
    for name in ("left", "right"):
        npt = nostril_L if name == "left" else nostril_R
        rep, cur = side_report(
            name, sides[name], a, npt, posterior, args.bin_mm,
            args.anterior_window_mm, args.entry_skip_mm)
        reports[name] = rep
        curves[name] = cur

    result = {
        "schema": "nasal_mca_measurement/v1",
        "case": case,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": {
            "script": os.path.abspath(__file__),
            "parameters": {
                "bin_mm": args.bin_mm,
                "anterior_window_mm": args.anterior_window_mm,
                "entry_skip_mm": args.entry_skip_mm,
                "posterior_axis_source": "anatomy_frame.posterior_lps (palate-plane frame)",
                "left_right_split": "TS semantic labels, not geometric midline",
            },
        },
        "inputs": {
            "candidate_mask": mask_p,
            "candidate_mask_sha256": sha256_file(mask_p),
            "landmarks": lm_p,
            "source_ct": ct_p if os.path.exists(ct_p) else None,
            "source_ct_sha256": sha256_file(ct_p) if os.path.exists(ct_p) else None,
        },
        "coordinate_system": "LPS",
        "unit": "mm",
        "voxel_volume_mm3": round(abs(float(np.linalg.det(a[:3, :3]))), 8),
        "posterior_lps": np.round(posterior, 6).tolist(),
        "method": (
            "A(s) = N(s) * V_voxel / ds, s = distance along posterior axis from ipsilateral nostril. "
            "CT equivalent of acoustic-rhinometry area-distance curve."
        ),
        "status": "provisional_geometry",
        "clinical_validation": "not_validated",
        "per_side": reports,
        "literature_reference": LITERATURE,
        "caveats": [
            "输入几何为 provisional 候选掩膜，未经 7 点人工复核，不构成本项目的验收结论。",
            "入口面尚未经人工确认；若 entry_boundary_artifact_suspected 为真，'incl_entry' 最小值"
            "是入口斜切伪影而非鼻阀，须以人工确认的入口裁剪面重测后才能定论。",
            "距鼻孔距离的起点取 TS 标签最前端，与 AR 的适配器起点定义不同，位置值不可直接与 AR 比较。",
            "截面积取垂直于前后轴的平面；真实流道并非严格沿该轴，故为近似。",
            "候选掩膜含鼻咽合并段，左右由 TS 语义标签分离，鼻咽段不参与 MCA 判定。",
            "文献参考值来自 AR(声反射)，与 CT 在体位、黏膜状态、起点定义上系统性有偏，只作量级哨兵。",
            "未使用中心线，也未做平滑；空 slab 如实报出不插值。",
        ],
    }

    out_json = os.path.join(out_d, f"mca_{case}.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    for name in ("left", "right"):
        dist, area, disc = curves[name]
        if dist.size == 0:
            continue
        csv_p = os.path.join(out_d, f"mca_curve_{case}_{name}.csv")
        with open(csv_p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["distance_from_nostril_mm", "area_mm2", "empty_slab"])
            for d, ar, dc in zip(dist, area, disc):
                w.writerow([round(float(d), 3), round(float(ar), 4), int(dc)])

    for name in ("left", "right"):
        r = reports[name]
        if r.get("mca_incl_entry_mm2") is None:
            print(f"[{case}] {name}: {r.get('status')}")
            continue
        flag = " ⚠入口伪影" if r.get("entry_boundary_artifact_suspected") else ""
        disc = f" | 断层 {r['discontinuity_slabs']} 处" if r["discontinuity_slabs"] else ""
        print(f"[{case}] {name}: 含入口 MCA={r['mca_incl_entry_mm2']:.1f} mm² "
              f"@ {r['mca_incl_entry_distance_mm']:.1f} mm{flag}")
        pe = r.get("mca_post_entry_mm2")
        if pe is not None:
            print(f"       跳过入口后 MCA={pe:.1f} mm² ({r['mca_post_entry_cm2']:.3f} cm²) "
                  f"@ {r['mca_post_entry_distance_mm']:.1f} mm "
                  f"| vs 亚洲参考 {LITERATURE['asian_adult_mca_cm2']} cm² "
                  f"= x{r.get('ratio_to_asian_reference')} [{r.get('magnitude_check')}]")
        print(f"       断层:{disc if disc else ' 无'}")
    print(f"[{case}] 输出: {out_json}")


if __name__ == "__main__":
    main()
