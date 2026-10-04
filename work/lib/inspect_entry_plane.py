# -*- coding: utf-8 -*-
"""CT ray measurements near proposed nostrils, without anatomical verdicts.

An open airway may continue into outside air without crossing tissue. A tissue
hit may belong to several structures. Neither ray length nor a single HU
threshold establishes the skin opening, a nasal valve, or missing vestibule.
Out-of-FOV samples remain NaN and are never replaced by edge voxels.
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import SimpleITK as sitk
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

from scipy import ndimage as ndi  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from measure_mca import _ascii_copy, sha256_file, LITERATURE  # noqa: E402
from auto_anatomy_landmarks import affine as sitk_affine  # noqa: E402

TISSUE_HU = -200      # 工程阈值；超阈值采样不等于已识别皮肤或其他结构
AIR_HU = -300         # 与全项目统一的空气阈值一致
FORWARD_MM = 30.0     # 沿 -posterior 采样长度；不据此判定体内/体外
STEP_MM = 0.35


def sample_hu(ct_arr, a, start_lps, direction, length_mm, step_mm=STEP_MM):
    d = np.asarray(direction, float)
    start = np.asarray(start_lps, float)
    a = np.asarray(a, float)
    if d.shape != (3,) or not np.all(np.isfinite(d)):
        raise ValueError('Direction must contain three finite components')
    norm = np.linalg.norm(d)
    if not np.isfinite(norm) or norm <= 0:
        raise ValueError('Direction must have a finite nonzero length')
    if (not np.isfinite(length_mm) or length_mm <= 0
            or not np.isfinite(step_mm) or step_mm <= 0):
        raise ValueError('Finite direction and positive ray dimensions required')
    if start.shape != (3,) or not np.all(np.isfinite(start)):
        raise ValueError('Ray origin must contain three finite LPS coordinates')
    if a.shape != (4, 4) or not np.all(np.isfinite(a)):
        raise ValueError('Affine must be a finite 4-by-4 matrix')
    if np.ndim(ct_arr) != 3 or 0 in ct_arr.shape:
        raise ValueError('CT array must be a nonempty three-dimensional volume')
    d = d / norm
    ss = np.arange(0.0, length_mm, step_mm)
    ss = np.append(ss, length_mm)
    pts = start[None, :] + ss[:, None] * d[None, :]
    inv = np.linalg.inv(a)
    ijk = pts @ inv[:3, :3].T + inv[:3, 3]
    vals = ndi.map_coordinates(ct_arr.astype(np.float32, copy=False), ijk[:, ::-1].T,
                              order=1, mode="constant", cval=np.nan)
    return ss, vals


def first_tissue_distance(ss, hu):
    """沿射线第一个 HU > TISSUE_HU 的距离；没有则 None。"""
    hu = np.asarray(hu, float)
    invalid = np.flatnonzero(~np.isfinite(hu))
    end = int(invalid[0]) if invalid.size else len(hu)
    hit = np.nonzero(hu[:end] > TISSUE_HU)[0]
    return float(ss[hit[0]]) if hit.size else None


def air_run_from_origin(ss, hu):
    """Last observed distance in the contiguous air run (a lower bound)."""
    if not len(hu) or not np.isfinite(hu[0]):
        return None
    for i in range(len(ss)):
        if not np.isfinite(hu[i]) or hu[i] >= AIR_HU:
            return float(ss[max(0, i - 1)])
    return float(ss[-1])


def analyse_side(ct_arr, a, point, posterior, side):
    fwd = -np.asarray(posterior, float)
    ss, hu = sample_hu(ct_arr, a, point, fwd, FORWARD_MM)

    d_tissue = first_tissue_distance(ss, hu)
    run = air_run_from_origin(ss, hu)

    valid = np.isfinite(hu)
    invalid = np.flatnonzero(~valid)
    prefix_end = int(invalid[0]) if invalid.size else len(hu)
    observed = float(ss[prefix_end - 1]) if prefix_end else 0.0
    if not valid[0]:
        verdict = "origin_outside_fov"
        verdict_zh = "候选起点不在可采样范围，不能评价该射线。"
    elif d_tissue is None:
        verdict = "no_tissue_hit_in_observed_ray"
        verdict_zh = f"已观测前向 {observed:.1f} mm 内未命中 HU>-200；这不能确定鼻孔边缘或入口深度。"
    else:
        verdict = "tissue_hit_in_observed_ray"
        verdict_zh = f"前向 {d_tissue:.1f} mm 命中 HU>-200；命中结构未识别，不能据此确认入口或鼻前庭缺失。"

    return {
        "side": side,
        "forward_tissue_distance_mm": None if d_tissue is None else round(d_tissue, 2),
        "air_run_from_point_mm": None if run is None else round(run, 2),
        "air_run_is_observed_lower_bound": run is not None,
        "observed_ray_mm": round(observed, 2),
        "fov_truncated": bool(not valid.all()),
        "anatomical_verdict": "undetermined",
        "verdict": verdict,
        "verdict_zh": verdict_zh,
        "hu_profile": {
            "distances_mm": np.round(ss, 2).tolist(),
            "hu": [round(float(v), 1) if np.isfinite(v) else None for v in hu],
        },
    }, (ss, hu)


def plot_case(case, out_png, sides, curve_csv, mca_json):
    fig, axes = plt.subplots(len(sides) + 1, 1, figsize=(9, 4 + 3 * len(sides)))
    if len(sides) == 1:
        axes = [axes[0], axes[1]] if isinstance(axes, np.ndarray) else [axes, axes[1]]
    ax0 = axes[0]
    ax0.set_title(f"{case} 入口区面积-距离曲线（放大）")
    for side in ("left", "right"):
        csv_p = curve_csv.format(side=side)
        if not os.path.exists(csv_p):
            continue
        rows = list(csv.reader(open(csv_p, encoding="utf-8")))[1:]
        d = [float(r[0]) for r in rows]
        a = [float(r[1]) for r in rows]
        ax0.plot(d, a, label=side)
    ax0.set_xlim(0, 15)
    ax0.set_xlabel("距鼻孔候选点 (mm)")
    ax0.set_ylabel("截面积 (mm²)")
    ax0.grid(alpha=0.3)
    ax0.legend()
    ref = LITERATURE["asian_adult_mca_cm2"] * 100
    ax0.axhline(ref, color="tab:red", ls="--", lw=1,
                label=f"亚洲参考 {ref:.0f} mm²")
    ax0.legend()

    for i, (side, (ss, hu)) in enumerate(sides.items(), start=1):
        ax = axes[i]
        ax.plot(ss, hu, lw=1.2)
        ax.axhline(TISSUE_HU, color="gray", ls=":", lw=0.8)
        ax.axhline(AIR_HU, color="gray", ls=":", lw=0.8)
        ax.axvline(0, color="tab:green", lw=1, label="候选点")
        invalid = np.flatnonzero(~np.isfinite(hu))
        if invalid.size:
            last_observed = max(0, int(invalid[0]) - 1)
            ax.axvspan(ss[last_observed], ss[-1], color="gray", alpha=0.18,
                       label="后续未连续观测")
        ax.set_title(f"{side} — 向前（-posterior）CT 值剖面；不识别命中结构")
        ax.set_xlabel("往前距离 (mm)")
        ax.set_ylabel("HU")
        ax.set_ylim(-1050, 200)
        ax.set_xlim(0, ss[-1])
        ax.grid(alpha=0.3)
        ax.legend()
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    import csv
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    case = args.case
    work = r"D:\项目\鼻腔建模\work"
    lm_p = os.path.join(work, "06_auto_landmarks", case, "landmarks.json")
    ct_p = os.path.join("C:\\", "ts_work", case, "ct.nii.gz")
    out_d = args.out_dir or os.path.join(work, "06_auto_landmarks", case)
    os.makedirs(out_d, exist_ok=True)

    with open(lm_p, encoding="utf-8") as f:
        lm = json.load(f)
    frame = lm["anatomy_frame"]
    posterior = np.asarray(frame["posterior_lps"], float)

    ct_img = sitk.ReadImage(_ascii_copy(ct_p))
    ct_arr = sitk.GetArrayFromImage(ct_img)
    a = sitk_affine(ct_img)

    sides, reports = {}, {}
    for side, key in (("left", "nostril_L"), ("right", "nostril_R")):
        pt = lm["landmarks"][key]["point_lps_mm"]
        rep, pack = analyse_side(ct_arr, a, pt, posterior, side)
        reports[side] = rep
        sides[side] = pack

    curve_csv = os.path.join(work, "05_ts_seg", case, "anatomy", "mca_curve_" + case + "_{side}.csv")
    png_p = os.path.join(out_d, f"entry_plane_check_{case}.png")
    plot_case(case, png_p, sides, curve_csv, None)

    result = {
        "schema": "entry_plane_check/v2",
        "case": case,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "沿 -posterior 射线采样 HU，量候选点到首个高于 HU 阈值采样的距离",
        "sampling": {"length_mm": FORWARD_MM, "step_mm": STEP_MM,
                     "interpolation": "linear", "outside_fov": "null",
                     "support": "within voxel-center bounds"},
        "thresholds": {"tissue_hu": TISSUE_HU, "air_hu": AIR_HU},
        "limitation": "射线 HU 只描述采样，不识别皮肤、鼻翼缘或鼻阀；不能据此证明入口正确、偏深或鼻前庭缺失。",
        "inputs": {"source_ct": ct_p, "source_ct_sha256": sha256_file(ct_p),
                   "landmarks": lm_p, "landmarks_sha256": sha256_file(lm_p)},
        "status": "engineering_check_not_medical_validation",
        "per_side": {k: {kk: vv for kk, vv in v.items() if kk != "hu_profile"}
                     for k, v in reports.items()},
        "hu_profiles": {k: v["hu_profile"] for k, v in reports.items()},
    }
    json_p = os.path.join(out_d, f"entry_plane_check_{case}.json")
    with open(json_p, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"[{case}]")
    for side, r in reports.items():
        print(f"  {side}: {r['verdict_zh']}")
    print(f"  图: {png_p}")
    print(f"  判定: {json_p}")
