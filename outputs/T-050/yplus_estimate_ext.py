# -*- coding: utf-8 -*-
"""
T-050 改约后 C1 重做：扩展域（t054 网格）y+ 估算
y+ = u_tau*y1/nu；u_tau = sqrt(tau_w/rho)
tau_w：T-054 扩展域实测 WSS（median 0.06824 / max 3.292 Pa，wss_t054_b15_oroext.json）
y1：t054 t600 体网格节点到壁面最近距离分布（本脚本实测）
原短域版见 yplus_estimate.py（结论 y+ 中位 ~6.5 → Spalding）；本版验证该选择在扩展网格仍成立。
"""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "work" / "lib"))
import flow_streamlines as _fs  # noqa: E402

# 扩展域出口 patch 名是 oropharynx_truncation_outlet，共享库常量仍是短域的
# nasopharynx_outlet；本脚本只用到 wall，故就地收窄 PATCH_FILES（不改共享库）。
_fs.PATCH_FILES = ("wall",)
from flow_streamlines import extract_field  # noqa: E402

HERE = Path(__file__).resolve().parent
RHO, NU = 1.2, 1.5e-5

f = extract_field(HERE / "vtk_t054_t600_ascii" / "foam_maxh1_600")
vol = f["pts"]
wall = f["wall_pts"]

tree = cKDTree(wall)
d, _ = tree.query(vol, k=1)
near = d[d < 2.0e-3]
y1 = {
    "p01": float(np.percentile(near, 1)),
    "p05": float(np.percentile(near, 5)),
    "median": float(np.median(near)),
    "p95": float(np.percentile(near, 95)),
    "n_nodes_lt_2mm": int(len(near)),
}

wss_src = json.loads((HERE.parent / "T-054" / "wss_t054_b15_oroext.json").read_text(encoding="utf-8"))
wss = {"median": wss_src["wss_median_pa"], "max": wss_src["wss_max_pa"]}
out = {"y1_m": y1, "wss_Pa": wss, "rho": RHO, "nu": NU, "domain": "b15_oropharynx_extended_t054",
       "mesh": "t054_b15_oroext maxh1.0 repaired (636,342 cells)", "yplus": {}}
for wk, wv in wss.items():
    utau = float(np.sqrt(wv / RHO))
    out["yplus"][wk] = {"u_tau": utau,
                        **{yk: utau * yv / NU for yk, yv in y1.items() if yk != "n_nodes_lt_2mm"}}
(HERE / "yplus_estimate_ext.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))
