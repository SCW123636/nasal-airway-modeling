# -*- coding: utf-8 -*-
"""
T-046 · PyVista 软件级渲染（GitHub 开源工具增强，回应「西门子效果」方向核验）
同一份真实场：internal.vtu + 四个 patch；PyVista(VTK 内核) 流线 + PBR 风格渲染静态图。
离屏渲染；失败则如实记录原因（不编造图）。
"""
import json
from pathlib import Path

import numpy as np
import pyvista as pv

HERE = Path(__file__).resolve().parent
VTK = HERE.parent / "T-044" / "vtk"

report = {}
try:
    mesh = pv.read(VTK / "internal.vtu")
    mesh.set_active_vectors("U")
    mesh["speed"] = np.linalg.norm(mesh["U"], axis=1)
    mesh.set_active_scalars("speed")

    wall = pv.read(VTK / "wall.vtp")
    srcL = pv.read(VTK / "nostril_L.vtp")
    srcR = pv.read(VTK / "nostril_R.vtp")

    rng = np.random.default_rng(7)
    def sub(src, n=60):
        pts = src.points
        sel = [int(rng.integers(len(pts)))]
        d = np.linalg.norm(pts - pts[sel[0]], axis=1)
        for _ in range(n - 1):
            sel.append(int(np.argmax(d)))
            d = np.minimum(d, np.linalg.norm(pts - pts[sel[-1]], axis=1))
        return pv.PolyData(pts[sel])

    sl = mesh.streamlines_from_source(sub(srcL), integration_direction="forward",
                                      max_length=500.0, terminal_speed=3e-3)
    sr = mesh.streamlines_from_source(sub(srcR), integration_direction="forward",
                                      max_length=500.0, terminal_speed=3e-3)
    report["lines_L"] = sl.n_cells
    report["lines_R"] = sr.n_cells
    for s in (sl, sr):  # 流线输出带 U，不带派生 speed——就地补算
        if s.n_cells and "speed" not in s.array_names:
            s["speed"] = np.linalg.norm(s["U"], axis=1)

    pl = pv.Plotter(off_screen=True, window_size=(1400, 900))
    pl.set_background("#f4f7f5")
    pl.add_mesh(wall, color="#c3cdda", opacity=0.16, smooth_shading=True)
    pl.add_mesh(srcL, color="#d62728", opacity=0.9)
    pl.add_mesh(srcR, color="#1f77b4", opacity=0.9)
    for s in (sl, sr):
        if s.n_cells:
            pl.add_mesh(s.tube(radius=0.00015, n_sides=8), scalars="speed",
                        cmap="turbo", clim=[0, 3.3], lighting=True,
                        scalar_bar_args={"title": "|U| (m/s)", "vertical": True,
                                         "title_font_size": 14, "label_font_size": 11})
    # 视角对齐 three.js 版默认（azim=-60/elev=30/up=+z）
    c = np.array([5.49e-3, -63.62e-3, -26.61e-3])  # 与 three.js 版同中心（m）
    theta, phi, dist = -np.pi / 3, np.pi / 3, 0.10
    pos = c + dist * np.array([np.sin(phi) * np.cos(theta), np.cos(phi), np.sin(phi) * np.sin(theta)])
    pl.camera_position = pv.CameraPosition(position=pos, focal_point=c, viewup=(0, 0, 1))
    pl.add_text("真实 CFD 场 · t004_diag time=400 · PyVista(VTK) 流线（未收敛，仅看形态）",
                font_size=11, color="#23332f")
    out = pl.screenshot(HERE / "pyvista_render.png", return_img=False)
    report["screenshot"] = "pyvista_render.png"
    report["status"] = "ok"
except Exception as exc:
    report["status"] = "failed"
    report["error"] = repr(exc)

(HERE / "pyvista_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
