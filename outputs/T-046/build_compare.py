# -*- coding: utf-8 -*-
"""
T-046 · 引擎对照（「从结果看」判据）：手写追踪 vs vtkStreamTracer（ParaView 内核）
输入：outputs/T-044/vtk（同一份真实场）
产出：compare.json（量化对照）+ 对照静态图 + vtk 引擎版交互 HTML
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "work" / "lib"))
from flow_streamlines import (build_streamlines_vtk, classify_endpoints,  # noqa: E402
                              extract_field, trace_lines, trace_lines_vtk)

HERE = Path(__file__).resolve().parent
VTK = HERE.parent / "T-044" / "vtk"

# 1) 手写引擎（复算，保证同进程对照）
field = extract_field(VTK)
lines_hand, core_hand = trace_lines(field)

# 2) vtk 引擎
lines_vtk = trace_lines_vtk(VTK)
core_vtk = classify_endpoints(field, lines_vtk)

# 3) 量化对照
def line_lengths(lines):
    return np.array([l["length_mm"] for l in lines])

lh, lv = line_lengths(lines_hand), line_lengths(lines_vtk)
cmp = {
    "hand": {"n_lines": core_hand["n_lines"], "reasons": core_hand["reasons"],
             "speed": core_hand["speed_mps"],
             "length_mm": {"median": float(np.median(lh)), "max": float(lh.max()),
                           "p10": float(np.percentile(lh, 10))},
             "n_points": core_hand["n_points_total"]},
    "vtk": {"n_lines": core_vtk["n_lines"], "reasons": core_vtk["reasons"],
            "speed": core_vtk["speed_mps"],
            "length_mm": {"median": float(np.median(lv)), "max": float(lv.max()),
                          "p10": float(np.percentile(lv, 10))},
            "n_points": core_vtk["n_points_total"],
            "vtk_termination_codes": {}},
}
for l in lines_vtk:
    cmp["vtk"]["vtk_termination_codes"][str(l["vtk_termination"])] = \
        cmp["vtk"]["vtk_termination_codes"].get(str(l["vtk_termination"]), 0) + 1
(HERE / "compare.json").write_text(json.dumps(cmp, ensure_ascii=False, indent=2), "utf-8")
print(json.dumps(cmp, ensure_ascii=False, indent=2))

# 4) 对照静态图：左右两幅三维轨迹 + 长度分布
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DengXian", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

fig = plt.figure(figsize=(13.5, 5.6), dpi=150)
for i, (lines, name, core) in enumerate(((lines_hand, "手写追踪（T-044 版）", core_hand),
                                         (lines_vtk, "vtkStreamTracer（ParaView 内核）", core_vtk))):
    ax = fig.add_subplot(1, 2, i + 1, projection="3d")
    for l in lines:
        p = l["pts_mm"]
        ax.plot(p[:, 0], p[:, 1], p[:, 2], lw=0.6,
                color="#2a9d4a" if l["reason"] == "reached_outlet" else "#b64e43", alpha=0.75)
    ax.view_init(azim=-60, elev=30)
    r = core["reasons"]
    ax.set_title("%s\n共 %d 条 · 抵达出口 %d · 出域 %d · 滞留 %d"
                 % (name, core["n_lines"], r.get("reached_outlet", 0),
                    r.get("exited_wall_region", 0), r.get("stall_near_wall", 0)), fontsize=10)
    ax.set_xlabel("x mm", fontsize=8); ax.set_ylabel("y mm", fontsize=8); ax.set_zlabel("z mm", fontsize=8)
    ax.tick_params(labelsize=7)
fig.suptitle("同一份真实场（t004_diag time=400）· 同种子 60/侧 · 绿=抵达鼻咽出口 红=未抵达", fontsize=11)
fig.tight_layout()
fig.savefig(HERE / "compare_engines.png", bbox_inches="tight")
print("写出 compare_engines.png")

# 5) vtk 引擎版交互 HTML（同模板，便于直接对照观感）
from demo_context import CONTEXT as ctx
from flow_streamlines import render_html  # noqa: E402
meta_vtk = dict(core_vtk)
meta_vtk["reasons"] = core_vtk["reasons"]
html = render_html(field, lines_vtk, meta_vtk, ctx)
(HERE / "streamlines_vtk_engine.html").write_text(html, encoding="utf-8")
print("写出 streamlines_vtk_engine.html")
