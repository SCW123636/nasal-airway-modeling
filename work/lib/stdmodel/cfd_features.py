# -*- coding: utf-8 -*-
"""cfd_features.py —— Layer C CFD 特征行装配（v0.1 = T-058 三例已验证切片）。

v0.1 只有 3 例（b15/b01/b02，T-058 三例全链 VERIFIED）。n=3 是切片不是
常模——所有 S1 输出必须带 n=3 明示（C-a 句式：我们的 3 例……）。
24 例 CFD 层阻塞于 D-0 口径裁定 + 多日 CPU 矩阵，另立卡。

四主特征（SAHF50 / 下鼻道峰值 WSS / 中鼻道占比 / 前端温降）v0.1 不产：
需热通量场与区域分解，属 v0.2（夹具已预注册：T-043 Graetz）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import CLINICAL_STATUS, SCHEMA_VERSION
from .schema import CONVENTIONS, FEATURES

ROOT = Path("D:/项目/鼻腔建模")
T058 = ROOT / "outputs/T-058"
CFD_CASES = ("b15", "b01", "b02")


def _read_json(p: Path) -> dict:
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def build_case_row(case: str) -> dict:
    m_p = T058 / f"metrics_t058_{case}_oroext.json"
    w_p = T058 / f"wss_t058_{case}.json"
    for p in (m_p, w_p):
        if not p.exists():
            raise FileNotFoundError(f"{case}: 缺输入 {p}")
    m, w = _read_json(m_p), _read_json(w_p)
    mm, ww = m["metrics"], w

    feats = {
        "delta_p_pa": mm["delta_p_pa"]["value"],
        "resistance_pa_s_ml": mm["resistance_R"]["value_pa_s_ml"],
        "wss_median_pa": ww["wss_median_pa"],
        "wss_p90_pa": ww["wss_p90_pa"],
        "wss_force_n": ww["wall_shear_force_n"],
        "mesh_cells": mm["domain"]["mesh_cells_repaired"],
    }
    for k in feats:
        assert k in FEATURES, f"schema 外特征: {k}"

    qc = {
        "converged": mm.get("converged"),
        "numerical_validation": mm.get("numerical_validation"),
        "m2_criteria": mm.get("m2_criteria"),
        "mass_imbalance_frac": mm.get("mass_imbalance_frac"),
        "final_initial_residuals": mm.get("final_initial_residuals"),
        "in_norm": True,  # 三例均为 T-058 已验证切片；未收敛状态随行元数据携带
        "exclude_reason": None,
    }
    return {
        "case": case,
        "layer": "C",
        "schema": SCHEMA_VERSION,
        "conventions": CONVENTIONS["C"],
        "features": feats,
        "detail": {
            "boundary_convention": m.get("boundary_convention"),
            "outlet_role": m.get("outlet_role"),
            "reconciliation": m.get("reconciliation"),
            "wss_mean_pa": ww.get("wss_mean_pa"),
            "wss_max_pa": ww.get("wss_max_pa"),
            "wall_area_mm2": ww.get("wall_area_mm2"),
        },
        "fingerprints": {
            "metrics_sha256": _sha(m_p),
            "wss_sha256": _sha(w_p),
        },
        "qc": qc,
        "clinical_status": CLINICAL_STATUS,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _sha(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
