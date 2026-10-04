# -*- coding: utf-8 -*-
"""鼻窦标签的 HU 构成、对称性，以及窦口通道的瓶颈宽度测量。

解决的问题
    G_sinus 需要每个鼻窦标注开口状态 open / closed / unknown。
    此前认为窦口只能全人工；本脚本给出可自动预筛的量：
    在 CT 空气域里，窦与鼻腔之间那条通道的**瓶颈半宽**（体素数）。

方法
    1. 取 ROI（鼻腔标签 ∪ 鼻窦标签，外扩 margin 体素）
    2. air = HU < -300
    3. 26 邻域连通：窦空气与鼻腔空气是否同一分量
    4. 逐级 3x3x3 腐蚀：腐蚀 k 次仍连通 => 通道半宽 >= k 体素
       断开时的 k 即瓶颈半宽上界，通道宽 ≈ 2 * k * spacing

判读口径（写死，不允许放宽）
    - 瓶颈半宽 >= 1 体素（k=1 仍连通）  -> candidate_open，需人工确认通道位置
    - 仅 k=0 连通                        -> subvoxel，26 邻域下可能只是对角接触
                                            或部分容积效应，判 unknown
    - 不连通                             -> closed_in_ct_air_domain

红线
    - 通道**位置**是否真是窦口，本脚本不判、不猜；只报告存在性与宽度。
    - 不使用形态学闭运算等"把缝补上"的操作去制造连通。

用法
    python work/lib/measure_sinus_ostia.py --case p0
    python work/lib/measure_sinus_ostia.py --case p1 --cranio-dir ... --labels-dir ...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import SimpleITK as sitk
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.dirname(HERE)

AIR_HU = -300
MARGIN_VOX = 15
MAX_EROSION = 6
STRUCT = np.ones((3, 3, 3), dtype=bool)


def _ascii_copy(path):
    """SimpleITK 读不了中文路径，先拷到 ASCII 临时文件。"""
    import shutil
    import tempfile

    ext = os.path.splitext(path)[1] or ".nii.gz"
    fd, tmp = tempfile.mkstemp(suffix=ext, prefix="nasal_")
    os.close(fd)
    shutil.copyfile(path, tmp)
    return tmp


def read_bool(path):
    tmp = None
    try:
        img = sitk.ReadImage(path)
    except Exception:
        tmp = _ascii_copy(path)
        img = sitk.ReadImage(tmp)
    arr = sitk.GetArrayFromImage(img)
    if tmp:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return arr > 0


def read_ct(path):
    """返回 (hu 数组, spacing mm)。"""
    tmp = None
    try:
        img = sitk.ReadImage(path)
    except Exception:
        tmp = _ascii_copy(path)
        img = sitk.ReadImage(tmp)
    arr = sitk.GetArrayFromImage(img)
    sp = img.GetSpacing()  # xyz
    if tmp:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return arr, (abs(float(sp[2])), abs(float(sp[1])), abs(float(sp[0])))


def bbox_slice(mask, margin):
    zs, ys, xs = np.where(mask)
    if zs.size == 0:
        return None
    z0, z1 = max(int(zs.min()) - margin, 0), int(zs.max()) + margin + 1
    y0, y1 = max(int(ys.min()) - margin, 0), int(ys.max()) + margin + 1
    x0, x1 = max(int(xs.min()) - margin, 0), int(xs.max()) + margin + 1
    return (slice(z0, z1), slice(y0, y1), slice(x0, x1))


def main(argv=None):
    ap = argparse.ArgumentParser(description="鼻窦 HU 构成与窦口瓶颈测量")
    ap.add_argument("--case", required=True)
    ap.add_argument("--ct", default=None)
    ap.add_argument("--labels-dir", default=None, help="TS head_glands 标签目录")
    ap.add_argument("--cranio-dir", default=None, help="craniofacial_structures 输出目录")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--air-hu", type=float, default=AIR_HU)
    ap.add_argument("--margin", type=int, default=MARGIN_VOX)
    ap.add_argument("--max-erosion", type=int, default=MAX_EROSION)
    ap.add_argument("--skip-nasal-hu", action="store_true",
                    help="同时输出鼻腔标签的 HU>0 占比做对照")
    args = ap.parse_args(argv)

    case = args.case
    ct_p = args.ct or os.path.join("C:\\", "ts_work", case, "ct.nii.gz")
    lab_d = args.labels_dir or os.path.join("C:\\", "ts_work", case, "masks")
    cra_d = args.cranio_dir or os.path.join("C:\\", "ts_work", case, "cranio")
    out_d = args.out_dir or os.path.join(WORK, "05_ts_seg", case, "anatomy")
    os.makedirs(out_d, exist_ok=True)

    if not os.path.isdir(cra_d):
        print(f"[{case}] 未找到 craniofacial 输出目录：{cra_d}")
        print("   先跑：totalsegmentator(..., task='craniofacial_structures', nr_thr_saving=1)")
        return 2

    hu, spacing = read_ct(ct_p)
    vox_ml = spacing[0] * spacing[1] * spacing[2] / 1000.0
    print(f"[{case}] CT {hu.shape}  spacing={tuple(round(s,4) for s in spacing)} mm")

    nasal = None
    for f in ("nasal_cavity_left.nii.gz", "nasal_cavity_right.nii.gz"):
        p = os.path.join(lab_d, f)
        if os.path.isfile(p):
            nasal = read_bool(p) if nasal is None else (nasal | read_bool(p))
    if nasal is None:
        print(f"[{case}] 缺鼻腔标签，无法做连通性判定")
        return 2

    results = {}
    for label in ("sinus_maxillary", "sinus_frontal"):
        p = os.path.join(cra_d, label + ".nii.gz")
        if not os.path.isfile(p):
            results[label] = {"label": label, "ostium_status": "label_file_missing"}
            continue
        msk = read_bool(p)
        n = int(msk.sum())
        if n == 0:
            results[label] = {"label": label, "voxels": 0, "ostium_status": "empty_label"}
            continue

        h = hu[msk]
        lab, ncomp = ndimage.label(msk, structure=STRUCT)
        sizes = np.sort(np.bincount(lab.ravel())[1:])[::-1][:5]

        rec = {
            "label": label,
            "voxels": n,
            "volume_ml": round(n * vox_ml, 3),
            "n_components": int(ncomp),
            "component_volumes_ml": [round(float(s * vox_ml), 3) for s in sizes],
            "symmetry_ratio": round(float(sizes[1] / sizes[0]), 4) if ncomp >= 2 else None,
            "hu_positive_fraction": round(float((h > 0).mean()), 5),
            "hu_mean": round(float(h.mean()), 1),
            "hu_p95": round(float(np.percentile(h, 95)), 1),
        }

        roi = nasal | msk
        sl = bbox_slice(roi, args.margin)
        air = (hu[sl] < args.air_hu)
        nc_c, msk_c = nasal[sl], msk[sl]

        # 与鼻腔标签的 26 邻域直接接触
        rec["direct_contact_voxels_with_nasal_label"] = int(
            (ndimage.binary_dilation(msk_c, structure=STRUCT) & nc_c).sum()
        )
        d_nc = ndimage.distance_transform_edt(~nc_c)
        rec["min_distance_to_nasal_label_mm"] = round(
            float(d_nc[msk_c].min()) * float(np.mean(spacing)), 3
        )

        # 瓶颈：逐级腐蚀
        connected_k = -1
        for k in range(0, args.max_erosion + 1):
            a = ndimage.binary_erosion(air, structure=STRUCT, iterations=k) if k else air
            l, _ = ndimage.label(a, structure=STRUCT)
            s_seed = l[nc_c & a]
            s_sin = l[msk_c & a]
            if np.intersect1d(s_seed[s_seed > 0], s_sin[s_sin > 0]).size:
                connected_k = k
            else:
                break
        rec["bottleneck_halfwidth_vox"] = connected_k if connected_k >= 0 else None
        if connected_k < 0:
            rec["ostium_status"] = "closed_in_ct_air_domain"
        elif connected_k == 0:
            rec["ostium_status"] = "subvoxel_unknown"
            rec["channel_width_mm_estimate"] = None
        else:
            rec["ostium_status"] = "candidate_open_position_unverified"
            rec["channel_width_mm_estimate"] = round(
                2.0 * connected_k * float(np.mean(spacing)), 3
            )
        rec["erosion_note"] = (
            "腐蚀 k 次后仍连通 => 通道半宽 >= k 体素；26 邻域下对角接触也算连通，"
            "故 k=0 不足以判定真实窦口"
        )
        results[label] = rec
        print(f"[{case}] {label}: {rec['volume_ml']} mL  "
              f"HU>0={rec['hu_positive_fraction']*100:.2f}%  "
              f"瓶颈半宽={rec['bottleneck_halfwidth_vox']} 体素  "
              f"-> {rec['ostium_status']}")

    nasal_hu = None
    if args.skip_nasal_hu:
        nasal_hu = round(float((hu[nasal] > 0).mean()), 5)

    payload = {
        "schema": "sinus_ostia_measurement/v1",
        "generated_by": "measure_sinus_ostia.py",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "case": case,
        "status": "provisional_not_anatomically_validated",
        "parameters": {
            "air_hu_threshold": args.air_hu,
            "connectivity": 26,
            "erosion_structure": "3x3x3",
            "max_erosion": args.max_erosion,
            "roi_margin_vox": args.margin,
        },
        "spacing_mm": [round(float(s), 4) for s in spacing],
        "source": {
            "ct": os.path.abspath(ct_p),
            "labels_dir": os.path.abspath(lab_d),
            "cranio_dir": os.path.abspath(cra_d),
        },
        "sinuses": results,
        "nasal_label_hu_positive_fraction": nasal_hu,
        "interpretation": {
            "candidate_open_position_unverified": (
                "空气域存在通道且瓶颈 >= 1 体素；通道位置是否真为窦口需人工看图确认"),
            "subvoxel_unknown": (
                "仅 k=0 连通，通道窄于 1 体素，可能是对角接触或部分容积效应，不得判为 open"),
            "closed_in_ct_air_domain": "在 HU<-300 空气域内与鼻腔不连通",
        },
        "limits": [
            "只测通道存在性与宽度，不判通道是不是窦口",
            "未做闭运算等补缝操作，不制造连通",
            "鼻窦体积未与文献对账，不作正常/异常判据",
        ],
    }
    out_p = os.path.join(out_d, "sinus_%s.json" % case)
    with open(out_p, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    print(f"[{case}] 写出 {out_p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
