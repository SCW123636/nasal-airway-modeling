# -*- coding: utf-8 -*-
"""geom_features.py —— Layer G 几何特征行装配（标准模型 v0.1 的 24 例输入）。

输入（全部是已验证生产链的产物，本模块只读不重算）：
- outputs/T-059/openings/bXX.json        auto_opening_pipeline 阶段 5 报告
- outputs/T-059/mca/mca_bXX.json         measure_mca.py 输出（T-059 批跑后逐例跑）
- outputs/T-059/surfaces/bXX/air_mask.nii.gz   T-058 起生产链保存的气域掩膜
- C:/ts_work/bXX/masks/*.nii.gz          TS 四标签（左右容积比用；只读）

QC 门（进常模准入，不过者排除并记账，不静默）：
- opening decision == auto_pass
- z 向体素间距 ≤ 0.6 mm（文献影像红线）
- 截断出口面积 ∈ [10,600] mm²（病态屏，非解剖验证）
- 双侧 MCA 可计算
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from . import CLINICAL_STATUS, SCHEMA_VERSION
from .schema import CONVENTIONS, FEATURES

ROOT = Path("D:/项目/鼻腔建模")
T059 = ROOT / "outputs/T-059"
MASKS = Path("C:/ts_work")
LABELS = ("nasal_cavity_left", "nasal_cavity_right", "nasopharynx", "oropharynx")
OUTLET_BAND = (10.0, 600.0)
Z_SPACING_GATE = 0.6


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(p: Path) -> dict:
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def label_volumes_mm3(case: str, voxel_vol: float) -> tuple[dict, dict]:
    """四标签体素计数 → 各段容积（mm³）。左右按 TS 语义标签，不用几何中缝
    （中缝已被三例交叉验证证伪，见 measure_mca.py:257）。"""
    vols, shas = {}, {}
    for lab in LABELS:
        p = MASKS / case / "masks" / f"{lab}.nii.gz"
        if not p.exists():
            raise FileNotFoundError(f"{case}: 缺标签 {p}")
        arr = sitk.GetArrayFromImage(sitk.ReadImage(str(p)))
        vols[lab] = float(np.count_nonzero(arr)) * voxel_vol
        shas[lab] = sha256_file(p)
    return vols, shas


def build_case_row(case: str) -> dict:
    op_p = T059 / "openings" / f"{case}.json"
    mca_p = T059 / "mca" / f"mca_{case}.json"
    air_p = T059 / "surfaces" / case / "air_mask.nii.gz"
    for p in (op_p, mca_p, air_p):
        if not p.exists():
            raise FileNotFoundError(f"{case}: 缺输入 {p}")

    op, mca = _read_json(op_p), _read_json(mca_p)
    air = sitk.ReadImage(str(air_p))
    spacing = [float(s) for s in air.GetSpacing()]  # SimpleITK: (x,y,z)
    z_spacing = spacing[2]
    voxel_vol = spacing[0] * spacing[1] * spacing[2]

    patches = op["patch_areas_mm2"]
    qc_src = op["surface_qc"]
    nostril_l = patches["nostril_L"]
    nostril_r = patches["nostril_R"]
    outlet = patches["oropharynx_truncation_outlet"]
    wall_area = qc_src["surface_area_mm2"] - (nostril_l + nostril_r + outlet)

    per_side = mca["per_side"]

    def _mca(side: str) -> tuple[float | None, str, bool]:
        r = per_side[side]
        if r.get("mca_post_entry_mm2") is not None:
            return r["mca_post_entry_mm2"], "post_entry", bool(r.get("entry_boundary_artifact_suspected"))
        if r.get("mca_incl_entry_mm2") is not None:
            return r["mca_incl_entry_mm2"], "incl_entry", True
        return None, "missing", True

    mca_l, src_l, flag_l = _mca("left")
    mca_r, src_r, flag_r = _mca("right")

    vols, label_shas = label_volumes_mm3(case, voxel_vol)
    lr = vols["nasal_cavity_left"] + vols["nasal_cavity_right"]
    vol_ratio = vols["nasal_cavity_left"] / lr if lr > 0 else None

    feats = {
        "nostril_area_L_mm2": nostril_l,
        "nostril_area_R_mm2": nostril_r,
        "outlet_area_mm2": outlet,
        "wall_area_mm2": round(wall_area, 3),
        "airway_volume_mm3": qc_src["signed_volume_mm3"],
        "mca_L_mm2": mca_l,
        "mca_R_mm2": mca_r,
        "vol_ratio_LR": round(vol_ratio, 4) if vol_ratio is not None else None,
        "voxel_z_spacing_mm": z_spacing,
    }
    for k in feats:
        assert k in FEATURES, f"schema 外特征: {k}"

    qc = {
        "opening_decision": op.get("decision"),
        "z_spacing_ok": z_spacing <= Z_SPACING_GATE,
        "outlet_in_band": OUTLET_BAND[0] <= outlet <= OUTLET_BAND[1],
        "mca_ok": mca_l is not None and mca_r is not None,
        "mca_source": {"L": src_l, "R": src_r},
        "mca_entry_artifact_flag": {"L": flag_l, "R": flag_r},
        "admitted_needs_review": bool(op.get("admitted_needs_review")),
    }
    exclude = []
    if qc["opening_decision"] != "auto_pass":
        exclude.append(f"opening:{qc['opening_decision']}")
    if not qc["z_spacing_ok"]:
        exclude.append(f"z_spacing:{z_spacing}")
    if not qc["outlet_in_band"]:
        exclude.append(f"outlet:{outlet}")
    if not qc["mca_ok"]:
        exclude.append("mca_missing")
    qc["in_norm"] = not exclude
    qc["exclude_reason"] = ";".join(exclude) if exclude else None

    return {
        "case": case,
        "layer": "G",
        "schema": SCHEMA_VERSION,
        "conventions": CONVENTIONS["G"],
        "features": feats,
        "detail": {
            "label_volumes_mm3": vols,
            "surface_qc": {k: qc_src.get(k) for k in
                           ("surface_area_mm2", "signed_volume_mm3", "triangles", "vertices")},
            "voxel_volume_mm3": voxel_vol,
            "voxel_spacing_xyz_mm": spacing,
        },
        "fingerprints": {
            "surface_sha256": op.get("surface_sha256"),
            "landmark_sha256": op.get("plane_source_sha256"),
            "air_mask_sha256": sha256_file(air_p),
            "labels_sha256": label_shas,
            "opening_report_sha256": sha256_file(op_p),
            "mca_report_sha256": sha256_file(mca_p),
        },
        "qc": qc,
        "clinical_status": CLINICAL_STATUS,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
