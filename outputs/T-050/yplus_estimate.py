# -*- coding: utf-8 -*-
"""
T-049 → T-050 前置：y+ 估算（判据 C1）
y+ = u_τ·y₁/ν；u_τ = sqrt(τ_w/ρ)
τ_w：T-042 实测 wallShearStress 分布（median 0.047 Pa / max 4.17 Pa，WSL 原档）
y₁：t600 体网格节点到壁面的最近距离分布（本脚本实测）
"""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "work" / "lib"))
from flow_streamlines import extract_field  # noqa: E402

HERE = Path(__file__).resolve().parent
RHO, NU = 1.2, 1.5e-5

f = extract_field(HERE.parent / "T-049" / "vtk" / "t600")
vol = f["pts"]
wall = f["wall_pts"]

tree = cKDTree(wall)
d, _ = tree.query(vol, k=1)
near = d[d < 2.0e-3]  # 近壁 2mm 内的体节点 ≈ 第一/二层网格中心
y1 = {
    "p01": float(np.percentile(near, 1)),
    "p05": float(np.percentile(near, 5)),
    "median": float(np.median(near)),
    "p95": float(np.percentile(near, 95)),
    "n_nodes_lt_2mm": int(len(near)),
}

# T-042 实测 WSS（Pa）：median 0.047 / max 4.17
wss = {"median": 0.047, "max": 4.17}
out = {"y1_m": y1, "wss_Pa": wss, "rho": RHO, "nu": NU, "yplus": {}}
for wk, wv in wss.items():
    utau = float(np.sqrt(wv / RHO))
    out["yplus"][wk] = {"u_tau": utau,
                        **{yk: utau * yv / NU for yk, yv in y1.items() if yk != "n_nodes_lt_2mm"}}
(HERE / "yplus_estimate.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))
