# -*- coding: utf-8 -*-
"""Blender 端验证：导入 STL → 网格质量检查 → 简化 → 导出"""
import os, subprocess, json

OUT = r"D:\项目\鼻腔建模\work\03_mesh"
BLENDER = r"D:\项目\鼻腔建模\软件\blender\blender.exe"
MESH_DIR = r"D:\项目\鼻腔建模\work\03_mesh"

script = os.path.join(OUT, "_blender_check.py")
code = r'''# -*- coding: utf-8 -*-
import bpy, bmesh, json, os, sys
from mathutils import Vector

OUT = r"D:\项目\鼻腔建模\work\03_mesh"
res = {}

def mesh_stats(obj):
    bm = bmesh.new(); bm.from_mesh(obj.data)
    s = {
        "verts": len(bm.verts), "edges": len(bm.edges), "faces": len(bm.faces),
        "boundary_edges": sum(1 for e in bm.edges if len(e.link_faces) == 1),
        "nonmanifold_edges": sum(1 for e in bm.edges if len(e.link_faces) > 2),
        "wire_edges": sum(1 for e in bm.edges if len(e.link_faces) == 0),
    }
    bm.free()
    return s

# 清场
bpy.ops.wm.read_factory_settings(use_empty=True)

results = {}
for stl_name in ["airway_raw.stl", "airway_smooth1.stl", "airway_smooth2.stl"]:
    stl_path = os.path.join(OUT, stl_name)
    if not os.path.exists(stl_path):
        results[stl_name] = {"error": "not found"}
        continue

    # 清场
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)

    # 导入 STL
    try:
        bpy.ops.wm.stl_import(filepath=stl_path)
    except Exception as e:
        results[stl_name] = {"import_error": str(e)}
        continue

    objs = [o for o in bpy.data.objects if o.type == "MESH"]
    if not objs:
        results[stl_name] = {"error": "no mesh imported"}
        continue

    obj = objs[0]
    stats_before = mesh_stats(obj)

    # 尺寸检查
    bpy.context.view_layer.update()
    bbox = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    dims = [max(v[i] for v in bbox) - min(v[i] for v in bbox) for i in range(3)]

    # 修复流程（EDIT 模式）
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    fix_log = {}
    for label, fn in [
        ("fill_holes", lambda: bpy.ops.mesh.fill_holes(sides=0)),
        ("remove_doubles", lambda: bpy.ops.mesh.remove_doubles(threshold=0.0001)),
        ("normals_make_consistent", lambda: bpy.ops.mesh.normals_make_consistent(inside=False)),
        ("dissolve_degenerate", lambda: bpy.ops.mesh.dissolve_degenerate(threshold=0.0001)),
    ]:
        try:
            fix_log[label] = str(fn())
        except Exception as e:
            fix_log[label] = "ERR:" + str(e)[:50]
    bpy.ops.object.mode_set(mode='OBJECT')
    stats_after = mesh_stats(obj)

    # 简化测试 (Decimate)
    dec_log = {}
    try:
        m = obj.modifiers.new("Dec", "DECIMATE")
        m.ratio = 0.3
        bpy.ops.object.modifier_apply(modifier=m.name)
        stats_dec = mesh_stats(obj)
        dec_log = {"ok": True, "after": stats_dec}
    except Exception as e:
        dec_log = {"ok": False, "err": str(e)[:60]}

    results[stl_name] = {
        "import_ok": True,
        "dims_mm": [round(d, 2) for d in dims],
        "before": stats_before,
        "fix_log": fix_log,
        "after_fix": stats_after,
        "decimate": dec_log,
    }

with open(os.path.join(OUT, "blender_check.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("BLENDER_CHECK_DONE")
'''
open(script, "w", encoding="utf-8").write(code)

r = subprocess.run([BLENDER, "-b", "--factory-startup", "-P", script],
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=600)
print("rc =", r.returncode)
outf = os.path.join(OUT, "blender_check.json")
if os.path.exists(outf):
    print(open(outf, encoding="utf-8").read())
else:
    print("未产出")
    print((r.stdout or "")[-1500:])
    print("ERR:", (r.stderr or "")[-800:])
