"""Independent T-027 audit; does not import or execute the T-026 implementation.

Read-only inputs. All results go into a new run directory under outputs/T-027.
LPS bounds distinguish foreground voxel centres from voxel support.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import platform
import sys
from datetime import datetime, timezone

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"):
    os.environ[_name] = "1"

import numpy as np
import SimpleITK as sitk

sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(1)
CASES = ("p0", "p1", "p2", "p3", "p3t1")
LABELS = ("nasal_cavity_left", "nasal_cavity_right", "nasopharynx", "oropharynx", "hypopharynx", "larynx_air")
BASE_LABELS = set(LABELS[:3])


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def geometry(im) -> dict:
    return {"size_xyz": list(im.GetSize()), "spacing_xyz_mm": list(im.GetSpacing()),
            "origin_lps_mm": list(im.GetOrigin()), "direction_row_major": list(im.GetDirection())}


def points_to_lps(points_xyz, im):
    # Independently use the affine formula p = origin + direction @ (index * spacing).
    d = np.asarray(im.GetDirection(), dtype=np.float64).reshape(3, 3)
    return np.asarray(im.GetOrigin()) + (np.asarray(points_xyz, dtype=np.float64) * np.asarray(im.GetSpacing())) @ d.T


def bounds_for_points(points_xyz, im):
    p = points_to_lps(points_xyz, im)
    lo, hi = p.min(axis=0), p.max(axis=0)
    half = np.abs(np.asarray(im.GetDirection()).reshape(3, 3)) @ (np.asarray(im.GetSpacing()) / 2)
    return {"centre_min_lps_mm": lo.tolist(), "centre_max_lps_mm": hi.tolist(),
            "support_min_lps_mm": (lo - half).tolist(), "support_max_lps_mm": (hi + half).tolist()}


def foreground_summary(mask_zyx, im):
    count = int(np.count_nonzero(mask_zyx))
    faces = {"x_index_0": int(np.count_nonzero(mask_zyx[:, :, 0])),
             "x_index_last": int(np.count_nonzero(mask_zyx[:, :, -1])),
             "y_index_0": int(np.count_nonzero(mask_zyx[:, 0, :])),
             "y_index_last": int(np.count_nonzero(mask_zyx[:, -1, :])),
             "z_index_0": int(np.count_nonzero(mask_zyx[0, :, :])),
             "z_index_last": int(np.count_nonzero(mask_zyx[-1, :, :]))}
    out = {"nonzero_voxels": count, "volume_mm3": count * float(np.prod(im.GetSpacing())),
           "face_voxel_counts": faces, "touches_any_grid_face": any(faces.values())}
    if count:
        z, y, x = np.nonzero(mask_zyx)
        points = np.column_stack((x, y, z))
        out["index_min_xyz"] = points.min(axis=0).tolist()
        out["index_max_xyz"] = points.max(axis=0).tolist()
        out.update(bounds_for_points(points, im))
    else:
        out.update({"index_min_xyz": None, "index_max_xyz": None, "centre_min_lps_mm": None,
                    "centre_max_lps_mm": None, "support_min_lps_mm": None, "support_max_lps_mm": None})
    return out


def matches(a, b):
    return {"size": a.GetSize() == b.GetSize(),
            "spacing": bool(np.allclose(a.GetSpacing(), b.GetSpacing(), rtol=0, atol=1e-6)),
            "origin": bool(np.allclose(a.GetOrigin(), b.GetOrigin(), rtol=0, atol=1e-6)),
            "direction": bool(np.allclose(a.GetDirection(), b.GetDirection(), rtol=0, atol=1e-6))}


def audit_case(case: str, root: Path):
    folder = root / case
    ct_path = folder / "ct.nii.gz"
    result = {"case": case, "case_identity": "engineering_case_id_only; patient_A_B_mapping_unknown",
              "ct": {"path": str(ct_path), "exists": ct_path.is_file()}, "labels": {}}
    if not ct_path.is_file():
        return result
    ct = sitk.ReadImage(str(ct_path))
    arr = sitk.GetArrayViewFromImage(ct)
    result["ct"].update({"sha256": digest(ct_path), "bytes": ct_path.stat().st_size,
                          "geometry": geometry(ct), "pixel_type": ct.GetPixelIDTypeAsString()})
    corners = list(itertools.product(*((0, s-1) for s in ct.GetSize())))
    result["ct"].update(bounds_for_points(corners, ct))
    result["ct"]["grid_axis_vectors_lps_mm"] = (np.asarray(ct.GetDirection()).reshape(3, 3) @ np.diag(ct.GetSpacing())).T.tolist()
    base = np.zeros(arr.shape, dtype=bool)
    oro = None
    all_base_available = True
    for name in LABELS:
        possible = sorted(folder.rglob(name + ".nii.gz")) + sorted(folder.rglob(name + ".nii"))
        entry = {"exists": bool(possible), "all_matching_paths": [str(p) for p in possible]}
        result["labels"][name] = entry
        if not possible:
            if name in BASE_LABELS:
                all_base_available = False
            continue
        if len(possible) != 1:
            entry["error"] = "ambiguous_label_path"
            if name in BASE_LABELS:
                all_base_available = False
            continue
        p = possible[0]
        im = sitk.ReadImage(str(p))
        label_arr = sitk.GetArrayViewFromImage(im)
        positive = label_arr > 0
        match = matches(ct, im)
        entry.update({"path": str(p), "sha256": digest(p), "bytes": p.stat().st_size,
                      "geometry": geometry(im), "geometry_matches_ct": match, "compatible": all(match.values()),
                      "value_range": [float(label_arr.min()), float(label_arr.max())],
                      "semantic": foreground_summary(positive, im)})
        if all(match.values()):
            air = positive & (arr < -300)
            entry["air_strict_lt_minus300"] = foreground_summary(air, ct)
            if name in BASE_LABELS:
                base |= positive
            if name == "oropharynx":
                oro = positive.copy()
        elif name in BASE_LABELS:
            all_base_available = False
    if all_base_available:
        baseline_air = base & (arr < -300)
        result["independent_sets"] = {"threshold_hu": -300, "threshold_operator": "<",
                                      "semantic_baseline": foreground_summary(base, ct),
                                      "air_baseline": foreground_summary(baseline_air, ct)}
        if oro is not None:
            added = oro & (arr < -300) & ~baseline_air
            extended = baseline_air | added
            result["independent_sets"].update({"oropharynx_air_added": foreground_summary(added, ct),
                                                "air_extended": foreground_summary(extended, ct),
                                                "baseline_missing_from_extended": int(np.count_nonzero(baseline_air & ~extended)),
                                                "new_outside_oropharynx_air": int(np.count_nonzero((extended & ~baseline_air) & ~(oro & (arr < -300))))})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", default=r"C:\ts_work")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    env = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version,
           "executable": sys.executable, "platform": platform.platform(), "numpy": np.__version__,
           "SimpleITK": sitk.Version_VersionString(), "threads": sitk.ProcessObject.GetGlobalDefaultNumberOfThreads(),
           "script_sha256": digest(Path(__file__)), "input_root": args.input_root,
           "command": [sys.executable, *sys.argv],
           "limits": ["No DICOM read", "No inference/mesh/solver/service action", "No anatomy completeness determination", "No symptom causality determination"]}
    dump(args.out / "environment.json", env)
    all_results = []
    for case in CASES:
        result = audit_case(case, Path(args.input_root))
        dump(args.out / (case + "_audit.json"), result)
        all_results.append(result)
        labels = result["labels"]
        print(json.dumps({"case": case, "ct_size": result["ct"].get("geometry", {}).get("size_xyz"),
                          "labels": {k: {"exists": v["exists"], "nonzero": v.get("semantic", {}).get("nonzero_voxels"),
                                         "compatible": v.get("compatible"), "face_touch": v.get("semantic", {}).get("touches_any_grid_face")} for k, v in labels.items()},
                          "air_baseline": result.get("independent_sets", {}).get("air_baseline", {}).get("nonzero_voxels"),
                          "added_oropharynx_air": result.get("independent_sets", {}).get("oropharynx_air_added", {}).get("nonzero_voxels")}, ensure_ascii=False), flush=True)
    dump(args.out / "all_cases_audit.json", all_results)


if __name__ == "__main__":
    main()
