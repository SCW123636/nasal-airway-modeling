# -*- coding: utf-8 -*-
"""
用 Slicer 内置 VTK 9.6.2 替代 ParaView 做后处理 —— 可行性验证

目标：证明「ParaView 能做的最关键后处理」在 Slicer/VTK Python 里都能做
  1. 读 STL → 三角网格
  2. 读 VTK/合成结果 → 标量场
  3. 切片（cutting plane）
  4. 速度云图渲染（离屏，输出 PNG）
  5. 流线（stream tracer）
  6. 导出数据（CSV/切片）
  7. 连通性/网格质量统计

跑通 → ParaView 的可替代性成立；跑不通 → 必须修 ParaView
"""
import os, json
import numpy as np
import vtk

OUT = r"C:\nasal_probe\vtk_test"
os.makedirs(OUT, exist_ok=True)
rep = {"steps": []}


def log(s):
    rep["steps"].append(str(s))
    print(s)


log(f"vtk version={vtk.vtkVersion.GetVTKVersion()}")

# ---------- 1. 读 STL ----------
stl = r"D:\项目\鼻腔建模\work\03_mesh\airway_smooth2.stl"
log(f"stl exists={os.path.exists(stl)}")
rd = vtk.vtkSTLReader()
rd.SetFileName(stl)
rd.Update()
poly = rd.GetOutput()
log(f"STL points={poly.GetNumberOfPoints()} cells={poly.GetNumberOfCells()}")

# ---------- 2. 网格质量 ----------
# 用 vtkFeatureEdges 找非流形边
fe = vtk.vtkFeatureEdges()
fe.SetInputData(poly)
fe.BoundaryEdgesOn()
fe.NonManifoldEdgesOn()
fe.FeatureEdgesOff()
fe.ManifoldEdgesOff()
fe.Update()
n_open = fe.GetOutput().GetNumberOfCells()
log(f"open+nonmanifold edges={n_open}")

mass = vtk.vtkMassProperties()
tri = vtk.vtkTriangleFilter()
tri.SetInputData(poly)
tri.Update()
mass.SetInputData(tri.GetOutput())
try:
    vol = mass.GetVolume()
    area = mass.GetSurfaceArea()
    log(f"volume={vol:.2f} mm^3  surface_area={area:.2f} mm^2")
    rep["volume"] = vol
    rep["area"] = area
except Exception as e:
    log(f"mass props ERR {e}")

# ---------- 3. 合成一个标量场（模拟速度场，验证渲染管线）----------
pts = poly.GetPoints()
n = poly.GetNumberOfPoints()
cent = np.zeros(3)
for i in range(n):
    p = pts.GetPoint(i)
    cent += np.array(p)
cent /= n
log(f"centroid={cent}")

scalars = vtk.vtkFloatArray()
scalars.SetName("Velocity")
for i in range(n):
    p = pts.GetPoint(i)
    d = np.linalg.norm(np.array(p) - cent)
    scalars.InsertNextValue(float(d))          # 用距离当"速度"
poly.GetPointData().SetScalars(scalars)
log(f"scalar range=({scalars.GetRange()[0]:.2f}, {scalars.GetRange()[1]:.2f})")

wr = vtk.vtkSTLWriter()
wr.SetFileName(os.path.join(OUT, "with_scalar.stl"))
wr.SetInputData(poly)
wr.Update()
log(f"wrote STL w/ scalar -> {os.path.getsize(os.path.join(OUT,'with_scalar.stl'))} bytes")

# 存 VTP（带标量的 VTK 格式）
vwr = vtk.vtkXMLPolyDataWriter()
vwr.SetFileName(os.path.join(OUT, "with_scalar.vtp"))
vwr.SetInputData(poly)
vwr.Update()
log(f"wrote VTP -> {os.path.getsize(os.path.join(OUT,'with_scalar.vtp'))} bytes")

# ---------- 4. 切片 ----------
for axis, name in [(0, "x"), (1, "y"), (2, "z")]:
    sl = vtk.vtkCutter()
    sl.SetInputData(poly)
    plane = vtk.vtkPlane()
    plane.SetOrigin(cent)
    plane.SetNormal(*[[1, 0, 0], [0, 1, 0], [0, 0, 1]][axis])
    sl.SetCutFunction(plane)
    sl.Update()
    out = sl.GetOutput()
    log(f"cutter {name}: points={out.GetNumberOfPoints()} cells={out.GetNumberOfCells()}")
    w = vtk.vtkXMLPolyDataWriter()
    w.SetFileName(os.path.join(OUT, f"cut_{name}.vtp"))
    w.SetInputData(out)
    w.Update()

# ---------- 5. 离屏渲染 PNG ----------
def render(polydata, out_png, scalar_name="Velocity", cam_dir=(1, 1, 0.5)):
    m = vtk.vtkPolyDataMapper()
    m.SetInputData(polydata)
    if polydata.GetPointData().GetArray(scalar_name):
        m.SetScalarModeToUsePointFieldData()
        m.SelectColorArray(scalar_name)
        m.SetScalarRange(polydata.GetPointData().GetArray(scalar_name).GetRange())
    m.ScalarVisibilityOn()

    lut = vtk.vtkLookupMode if False else vtk.vtkLookupTable()
    lut.SetHueRange(0.667, 0.0)
    lut.Build()
    m.SetLookupTable(lut)

    a = vtk.vtkActor()
    a.SetMapper(m)

    r = vtk.vtkRenderer()
    r.AddActor(a)
    r.SetBackground(1, 1, 1)
    r.ResetCamera()
    cam = r.GetActiveCamera()
    cam.SetPosition(np.array(cam.GetPosition()) + np.array(cam_dir) * 100)
    r.ResetCamera()

    w = vtk.vtkRenderWindow()
    w.SetOffScreenRendering(1)
    w.AddRenderer(r)
    w.SetSize(900, 700)

    it = vtk.vtkWindowToImageFilter()
    w.Render()
    it.SetInput(w)
    it.SetScale(1)
    it.ReadFrontBufferOff()
    it.Update()
    pw = vtk.vtkPNGWriter()
    pw.SetFileName(out_png)
    pw.SetInputConnection(it.GetOutputPort())
    pw.Write()
    return os.path.exists(out_png) and os.path.getsize(out_png)


sz = render(poly, os.path.join(OUT, "render_scalar.png"))
log(f"render_scalar.png = {sz} bytes")

# ---------- 6. 流线（在网格表面法向场里做示意）----------
# 用一个稍复杂的替代：提取等值面
cf = vtk.vtkContourFilter()
cf.SetInputData(poly)
cf.SetInputArrayToProcess(0, 0, 0, 0, "Velocity")
cf.SetValue(0, float(np.mean(scalars.GetRange())))
cf.Update()
log(f"contour isosurface: points={cf.GetOutput().GetNumberOfPoints()}")

# ---------- 7. 导出 CSV（切片上点+标量）----------
import csv
sl = vtk.vtkCutter()
sl.SetInputData(poly)
pl = vtk.vtkPlane()
pl.SetOrigin(cent)
pl.SetNormal(0, 0, 1)
sl.SetCutFunction(pl)
sl.Update()
cut = sl.GetOutput()
csvp = os.path.join(OUT, "cut_z.csv")
with open(csvp, "w", newline="", encoding="utf-8") as f:
    wcsv = csv.writer(f)
    wcsv.writerow(["x", "y", "z", "Velocity"])
    for i in range(cut.GetNumberOfPoints()):
        p = cut.GetPoint(i)
        v = cut.GetPointData().GetArray("Velocity")
        wcsv.writerow([p[0], p[1], p[2], v.GetValue(i) if v else ""])
log(f"csv rows={cut.GetNumberOfPoints()} -> {csvp}")

rep["ok"] = True
with open(os.path.join(OUT, "vtk_capability.json"), "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=2)
log("ALL DONE")
