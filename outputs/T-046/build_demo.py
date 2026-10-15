# -*- coding: utf-8 -*-
"""
T-046 · 演示 + 回归：对 T-044 的真实 vtk 跑新版生成器
判据 C1：107 条流线 / 36 条抵达出口 / 速度范围与 trace_meta.json 逐位一致。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "work" / "lib"))
from flow_streamlines import build_streamlines  # noqa: E402

HERE = Path(__file__).resolve().parent
VTK = HERE.parent / "T-044" / "vtk"

from demo_context import CONTEXT as context

meta = build_streamlines(VTK, HERE / "streamlines_demo.html", HERE / "streamlines_demo_meta.json", context)

# C1 对账：与 T-044 的 trace_meta.json 逐位比对
ref = json.loads((HERE.parent / "T-044" / "trace_meta.json").read_text(encoding="utf-8"))
checks = {
    "n_lines": (meta["n_lines"], ref["n_lines"]),
    "reached_outlet": (meta["reasons"].get("reached_outlet"), ref["reasons"].get("reached_outlet")),
    "reasons": (meta["reasons"], ref["reasons"]),
    "speed_min": (meta["speed_mps"]["min"], ref["speed_mps"]["min"]),
    "speed_median": (meta["speed_mps"]["median"], ref["speed_mps"]["median"]),
    "speed_max": (meta["speed_mps"]["max"], ref["speed_mps"]["max"]),
    "n_points_total": (meta["n_points_total"], ref["n_points_total"]),
}
ok = all(a == b for a, b in checks.values())
report = {"C1_pass": ok, "checks": {k: {"new": a, "ref": b, "equal": a == b}
                                    for k, (a, b) in checks.items()}}
(HERE / "c1_regression.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
