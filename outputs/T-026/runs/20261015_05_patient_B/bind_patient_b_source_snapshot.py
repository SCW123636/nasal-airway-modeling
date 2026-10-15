"""Full HU and physical-geometry comparison; DICOM pixels ONLY via approved loader."""
from __future__ import annotations

import os
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "1"
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pydicom
import SimpleITK as sitk
import upper_airway_candidate as tool

sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(1)
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "work" / "lib"))
from dicom_sitk import load_series_sitk


def fingerprints(paths):
    return [{"path": str(p), "bytes": p.stat().st_size, "sha256": tool.sha256(p)} for p in paths]


def direction_from_headers(iops, positions):
    iops, positions = np.asarray(iops, float), np.asarray(positions, float)
    if iops.ndim != 2 or iops.shape[1] != 6 or len(iops) < 2 or positions.shape != (len(iops), 3):
        raise ValueError("header_geometry_shape_invalid")
    if not np.allclose(iops, iops[0], rtol=0, atol=1e-6):
        raise ValueError("IOP_changes_within_series")
    x, y = iops[0, :3], iops[0, 3:]
    normal = np.cross(x, y)
    if not (np.isclose(np.linalg.norm(x), 1) and np.isclose(np.linalg.norm(y), 1) and np.isclose(np.dot(x, y), 0)):
        raise ValueError("IOP_not_orthonormal")
    differences = np.diff(positions, axis=0)
    projected = differences @ normal
    if not (np.all(projected > 0) or np.all(projected < 0)):
        raise ValueError("IPP_not_monotonic_along_normal")
    signed_dz = float(np.median(projected))
    if not np.allclose(projected, signed_dz, rtol=0, atol=1e-4):
        raise ValueError("nonuniform_IPP_spacing")
    off_normal = differences - projected[:, None] * normal
    if not np.allclose(off_normal, 0, rtol=0, atol=1e-4):
        raise ValueError("IPP_has_unmodelled_inplane_drift")
    z = normal * np.sign(signed_dz)
    return np.column_stack([x, y, z]), abs(signed_dz), projected


def self_test(out):
    iops = [[0, 1, 0, 1, 0, 0]] * 3
    positions = [[7, 8, 30], [7, 8, 28], [7, 8, 26]]
    direction, dz, projected = direction_from_headers(iops, positions)
    assert np.array_equal(direction, [[0, 1, 0], [1, 0, 0], [0, 0, -1]])
    assert dz == 2 and np.array_equal(projected, [2, 2])
    reverse, reverse_dz, _ = direction_from_headers(iops, positions[::-1])
    assert np.array_equal(reverse[:, 2], [0, 0, 1]) and reverse_dz == 2
    checks = [{"name": "handwritten_IOP_IPP_cross_product_and_signed_order", "pass": True},
              {"name": "reverse_IPP_order_reverses_z_direction_without_SliceThickness", "pass": True}]
    try:
        direction_from_headers(iops, [[7,8,30],[7,8,28],[7,8,25]])
    except ValueError as exc:
        assert str(exc) == "nonuniform_IPP_spacing"
        checks.append({"name": "nonuniform_spacing_rejected", "pass": True})
    else:
        raise AssertionError("nonuniform_spacing_accepted")
    tool.write_json(out / "binding_known_answers.json", {"all_pass": True, "checks": checks,
        "fixture_source": "handwritten IOP/IPP vectors in bind_patient_b.py; no patient data"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dicom-series", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path(r"C:\ts_work"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    if Path(__file__).resolve().parents[1] not in out.parents:
        raise ValueError("output_must_be_inside_T026")
    out.mkdir(parents=True, exist_ok=False)
    tool.write_json(out / "environment.json", {**tool.environment(), "binding_tool_sha256": tool.sha256(__file__),
        "approved_DICOM_loader": str(REPO / "work/lib/dicom_sitk.py"),
        "approved_DICOM_loader_sha256": tool.sha256(REPO / "work/lib/dicom_sitk.py")})
    for source in (Path(__file__), Path(tool.__file__)):
        (out / (source.stem + "_source_snapshot.py")).write_bytes(source.read_bytes())
    tool.write_json(out / "reproduction.json", {"argv": [sys.executable, str(Path(__file__).resolve()),
        "--dicom-series", str(args.dicom_series), "--data-root", str(args.data_root), "--out", str(out)],
        "rerun_note": "Choose new --out; existing directory is rejected"})
    try:
        self_test(out)
        tool.synthetic_tests(out)
        names = list(sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(args.dicom_series)))
        if not names:
            raise ValueError("DICOM_series_files_not_found")
        source_paths = [Path(p) for p in names]
        source_paths += [args.data_root / "p2" / "ct.nii.gz"]
        source_paths += [args.data_root / "p2" / "masks" / (n + ".nii.gz") for n in tool.AUDIT_LABELS
                         if (args.data_root / "p2" / "masks" / (n + ".nii.gz")).is_file()]
        before = fingerprints(source_paths)
        tool.write_json(out / "input_fingerprints_before.json", before)
        # Header reads explicitly stop before pixels. No patient names, IDs or UIDs are collected.
        headers = []
        for name in names:
            ds = pydicom.dcmread(name, stop_before_pixels=True)
            headers.append({"file_basename": Path(name).name,
                "IOP": [float(v) for v in ds.ImageOrientationPatient],
                "IPP_LPS_mm": [float(v) for v in ds.ImagePositionPatient],
                "PixelSpacing_row_col_mm": [float(v) for v in ds.PixelSpacing],
                "Rows": int(ds.Rows), "Columns": int(ds.Columns)})
        tool.write_json(out / "coordinate_headers_no_identity.json", {"order": "approved loader's GDCM series filename order", "frames": headers})
        direction, dz, projected = direction_from_headers([x["IOP"] for x in headers], [x["IPP_LPS_mm"] for x in headers])
        print(json.dumps({"phase": "headers", "files": len(names), "dz_from_IPP_mm": dz}), flush=True)
        volume, spacing, origin, _ = load_series_sitk(str(args.dicom_series), verbose=False)
        target_image = sitk.ReadImage(str(args.data_root / "p2" / "ct.nii.gz"))
        target = sitk.GetArrayFromImage(target_image)
        shapes_equal = volume.shape == target.shape
        values_equal = bool(shapes_equal and np.array_equal(volume, target))
        spacing_equal = bool(np.allclose(spacing, target_image.GetSpacing(), rtol=0, atol=1e-6))
        origin_equal = bool(np.allclose(origin, target_image.GetOrigin(), rtol=0, atol=1e-4))
        direction_equal = bool(np.allclose(direction, np.asarray(target_image.GetDirection()).reshape(3, 3), rtol=0, atol=1e-6))
        row_col = np.asarray([x["PixelSpacing_row_col_mm"] for x in headers])
        pixel_spacing_consistent = bool(np.allclose(row_col, row_col[0], rtol=0, atol=1e-6))
        header_spacing = [float(row_col[0, 1]), float(row_col[0, 0]), dz]
        header_loader_spacing_agrees = bool(np.allclose(header_spacing, spacing, rtol=0, atol=1e-4))
        header_loader_origin_agrees = bool(np.allclose(headers[0]["IPP_LPS_mm"], origin, rtol=0, atol=1e-4))
        matches = all((values_equal, spacing_equal, origin_equal, direction_equal, pixel_spacing_consistent,
                       header_loader_spacing_agrees, header_loader_origin_agrees))
        report = {"user_designated_source": str(args.dicom_series), "candidate_existing_CT": str(args.data_root / "p2" / "ct.nii.gz"),
            "binding_scope": "full decoded HU array and physical voxel geometry equality within stated tolerances; not original DICOM file identity",
            "all_voxels_HU_exactly_equal": values_equal, "shape_equal": shapes_equal,
            "decoded_source_shape_zyx": volume.shape, "existing_CT_shape_zyx": target.shape,
            "decoded_voxel_count": int(volume.size), "source_dtype": str(volume.dtype), "existing_CT_dtype": str(target.dtype),
            "source_decoded_array_sha256": hashlib.sha256(volume.tobytes(order="C")).hexdigest(),
            "existing_CT_array_sha256": hashlib.sha256(target.tobytes(order="C")).hexdigest(),
            "mismatched_voxels": int(np.count_nonzero(volume != target)) if shapes_equal else None,
            "max_abs_HU_difference": float(np.max(np.abs(volume.astype(np.float32) - target.astype(np.float32)))) if shapes_equal else None,
            "spacing_equal_atol_1e_6_mm": spacing_equal, "origin_equal_atol_1e_4_mm": origin_equal,
            "direction_equal_atol_1e_6": direction_equal, "header_pixel_spacing_consistent": pixel_spacing_consistent,
            "header_loader_spacing_agrees_atol_1e_4_mm": header_loader_spacing_agrees,
            "header_loader_origin_agrees_atol_1e_4_mm": header_loader_origin_agrees,
            "source_loader_spacing_xyz_mm": spacing, "source_loader_origin_LPS_mm": origin,
            "source_direction_from_all_IOP_IPP": direction.tolist(), "source_dz_from_IPP_mm": dz,
            "IPP_dz_min_max_mm": [float(projected.min()), float(projected.max())],
            "source_SliceThickness_used": False, "existing_CT_geometry": tool.geometry(target_image),
            "source_bound_to_p2_HU_and_geometry": matches, "clinical_anatomy_and_outlet_review": "not_reviewed"}
        tool.write_json(out / "patient_B_source_binding.json", report)
        print(json.dumps({"phase": "full_HU_geometry_binding", "matches": matches, "mismatched_voxels": report["mismatched_voxels"]}), flush=True)
        del volume, target
        if matches:
            audit = tool.audit_case(args.data_root, "p2", out)
            result = tool.candidate(args.data_root, "p2", out, source_binding={"report": "patient_B_source_binding.json",
                "user_source_path": str(args.dicom_series), "binding_scope": report["binding_scope"]})
            oral = result["profiles"].get("nasal_oropharynx", {})
            ct_sha = next(x["sha256"] for x in before if x["path"] == str(args.data_root / "p2" / "ct.nii.gz"))
            review = ["# 患者 B 来源绑定候选·专业复核请求（未审核）", "",
                "- 用户指定患者 B 来源的完整 HU 与 p2 CT 逐位相同且物理网格相符；详 patient_B_source_binding.json。不是原始 DICOM 文件字节身份结论。",
                "- 当前候选：p2，未裁剪语义标签∩HU < -300；阈值探索；不等同生产最终 STL。",
                "- CT SHA-256：" + ct_sha, "- 口咽扩展候选 SHA-256：" + str(oral.get("sha256")),
                "- 原始 DICOM、标签完整指纹：input_fingerprints_before.json；预览：p2_original_vs_oropharynx.png。",
                "- 下咽标签为空、larynx_air 文件缺失。口咽空气接触 CT 下方扫描边缘；不能支持完整下咽/喉/声门覆盖。", "",
                "请王湧瑞确认并记录：", "", "1. 症状具体部位与所需研究范围（用户已指定 B，尚未提供精确症状定位）。",
                "2. 该扫描是否足以覆盖目标；是否需补充覆盖下咽、喉部或声门的影像。",
                "3. 鼻咽—口咽连续性与口腔排除，是否有需要修改的解剖范围。",
                "4. 下界/出口在患者 LPS mm 坐标中的位置、方向和依据；本候选没有确认或冻结出口。",
                "5. 认可结果与限制；日期、复核人、截图/标记证据。", "",
                "默认状态：未审核。当前不能作为已审核或 CFD 准入输入。", ""]
            (out / "患者B专业复核请求.md").write_text("\n".join(review), encoding="utf-8")
        after = fingerprints(source_paths)
        tool.write_json(out / "input_fingerprints_after.json", after)
        tool.write_json(out / "input_integrity.json", {"all_inputs_unchanged": before == after, "full_content_sha256": True})
        assert before == after, "input_fingerprint_changed"
        tool.write_json(out / "run_result.json", {"execution_finished": True, "source_binding_matches": matches,
            "all_inputs_unchanged": True, "review": "not_reviewed", "CFD_admitted": False,
            "requires_Lead_and_fresh_independent_acceptance": True})
        print(json.dumps({"phase": "patient_B_artifacts_written", "out": str(out)}), flush=True)
    except Exception as exc:
        tool.write_json(out / "run_failure.json", {"error_type": type(exc).__name__, "message": str(exc)})
        raise


if __name__ == "__main__":
    main()
