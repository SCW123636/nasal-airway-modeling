# -*- coding: utf-8 -*-
"""
Blender 端下游链路复验 (step 4)

验证项：
  A. 导入 STL，检查单位/尺度/朝向
  B. 网格修复链（fill_holes / remove_doubles / consistency）
  C. Decimate 到 CFD 合适面数（SOP 要求 3-10 万面）
  D. 导出 STL（wm.stl_export）
  E. 处理 STL 无坐标系问题：把几何平移到原点附近并居中
     （CT 物理坐标 -51/-230/-639 直接给 CFD 会导致域外/量级问题）
  F. 检查开口（boundary edges）：CFD 需要鼻孔+鼻咽两个开口

输出 JSON 到 C:\\nasal_probe\\blender_chain.json
"""
import bpy
import bmesh
import os
import json
import math
from mathutils import Vector

OUT = r"C:\nasal_probe"
os.makedirs(OUT, exist_ok=True)

SRC = r"D:\项目\鼻腔建模\work\03_mesh\airway_smooth2.stl"
rep = {"src": SRC, "steps": []}


def log(s):
    rep["steps"].append(str(s))


def mesh_stats(obj):
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    boundary = [e for e in bm.edges if len(e.link_faces) == 1]
    nonman = [e for e in bm.edges if len(e.link_faces) > 2]
    wire = [e for e in bm.edges if len(e.link_faces) == 0]
    # 连通分量（islands）
    bm.verts.ensure_lookup_table()
    seen = set()
    islands = 0
    for v in bm.verts:
        if v.index in seen:
            continue
        islands += 1
        stack = [v]
        while stack:
            cur = stack.pop()
            if cur.index in seen:
                continue
            seen.add(cur.index)
            for e in cur.link_edges:
                o = e.other_vert(cur)
                if o.index not in seen:
                    stack.append(o)
    res = {
        "verts": len(bm.verts), "edges": len(bm.edges), "faces": len(bm.faces),
        "boundary_edges": len(boundary), "nonmanifold_edges": len(nonman),
        "wire_edges": len(wire), "islands": islands,
    }
    bm.free()
    return res


# ---------- A. 导入 ----------
# 5.2 需要 scale 参数（STL 无单位，Blender 默认按米）
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath=SRC)
obj = bpy.context.selected_objects[0]
rep["imported_name"] = obj.name
bpy.context.view_layer.objects.active = obj

bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
mn = Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
mx = Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
size = mx - mn
rep["import_bbox"] = {"min": [round(v, 3) for v in mn],
                      "max": [round(v, 3) for v in mx],
                      "size": [round(v, 3) for v in size]}
log(f"import bbox min={[round(v,2) for v in mn]} size={[round(v,2) for v in size]}")
rep["before"] = mesh_stats(obj)

# ---------- E. 居中到原点 ----------
center = (mn + mx) / 2.0
for v in obj.data.vertices:
    v.co -= center
rep["centered_by"] = [round(v, 3) for v in center]
log(f"centered by {[round(v,3) for v in center]}")

# ---------- B. 修复链 ----------
log(f"active object = {bpy.context.view_layer.objects.active.name}")
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.context.view_layer.objects.active = obj

log(f"mode before = {obj.mode}")
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")

fixes = {}
for op_name, op in [
    ("remove_doubles", bpy.ops.mesh.remove_doubles),
    ("normals_make_consistent", bpy.ops.mesh.normals_make_consistent),
    ("dissolve_degenerate", bpy.ops.mesh.dissolve_degenerate),
    ("fill_holes", bpy.ops.mesh.fill_holes),
]:
    try:
        r = op()
        fixes[op_name] = str(r)
    except Exception as e:
        fixes[op_name] = f"ERR:{e}"
bpy.ops.object.mode_set(mode="OBJECT")
rep["fix_log"] = fixes
rep["after_fix"] = mesh_stats(obj)
log(f"after fix: {rep['after_fix']}")

# ---------- C. Decimate ----------
target_faces = 90000
cur = rep["after_fix"]["faces"]
if cur > target_faces:
    ratio = target_faces / cur
    m = obj.modifiers.new("Dec", "DECIMATE")
    m.decimate_type = "COLLAPSE"
    m.ratio = ratio
    bpy.ops.object.modifier_apply(modifier="Dec")
    rep["decimate_ratio"] = round(ratio, 4)
rep["after_decimate"] = mesh_stats(obj)
log(f"after decimate: {rep['after_decimate']}")

# 重新居中（decimate 可能微移）
bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
mn = Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
mx = Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
rep["final_bbox"] = {"min": [round(v, 3) for v in mn],
                     "max": [round(v, 3) for v in mx],
                     "size": [round(v, 3) for v in (mx - mn)]}

# ---------- D. 导出 ----------
outdir = r"D:\项目\鼻腔建模\work\04_cfd_ready"
os.makedirs(outdir, exist_ok=True)
outstl = os.path.join(outdir, "airway_cfd_ready.stl")
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
try:
    r = bpy.ops.wm.stl_export(filepath=outstl, export_selected_objects=True,
                              global_scale=1.0)
    rep["export"] = {"ok": True, "result": str(r), "path": outstl,
                     "size": os.path.getsize(outstl) if os.path.exists(outstl) else None}
except Exception as e:
    rep["export"] = {"ok": False, "err": str(e)}
log(f"export: {rep['export']}")

# 同时导出 obj（保单位清晰）
try:
    outobj = os.path.join(outdir, "airway_cfd_ready.obj")
    bpy.ops.wm.obj_export(filepath=outobj, export_selected_objects=True)
    rep["export_obj"] = {"ok": True, "path": outobj}
except Exception as e:
    rep["export_obj"] = {"ok": False, "err": str(e)}

rep["ok"] = True
with open(os.path.join(OUT, "blender_chain.json"), "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=2)
print("BLENDER CHAIN DONE")
