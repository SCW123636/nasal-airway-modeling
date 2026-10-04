# -*- coding: utf-8 -*-
"""Blender 渲染鼻腔模型 3D 预览图"""
import os, subprocess, json

OUT = r"D:\项目\鼻腔建模\work\03_mesh"
BLENDER = r"D:\项目\鼻腔建模\软件\blender\blender.exe"
MESH = os.path.join(OUT, "airway_smooth2.stl")

script = os.path.join(OUT, "_blender_render.py")
code = r'''# -*- coding: utf-8 -*-
import bpy, math, os
from mathutils import Vector

OUT = r"D:\项目\鼻腔建模\work\03_mesh"
MESH = r"D:\项目\鼻腔建模\work\03_mesh\airway_smooth2.stl"

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath=MESH)

objs = [o for o in bpy.data.objects if o.type == "MESH"]
obj = objs[0]
bpy.context.view_layer.update()

# 居中
bbox = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
center = sum(bbox, Vector((0,0,0))) / 8
obj.location = obj.location - center
bpy.context.view_layer.update()

# 视图方向设置
scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 1200
scene.render.resolution_y = 900
scene.render.film_transparent = False
scene.world = bpy.data.worlds.new("W")
scene.world.use_nodes = True
bg = scene.world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.05, 0.07, 0.1, 1)
bg.inputs[1].default_value = 1.0

# 材质
mat = bpy.data.materials.new("M")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.85, 0.35, 0.35, 1)
bsdf.inputs["Metallic"].default_value = 0.3
bsdf.inputs["Roughness"].default_value = 0.4
obj.data.materials.append(mat)

# 灯光
for loc, energy in [((5, -5, 5), 2000), ((-5, -3, 3), 1200), ((0, 5, 4), 800)]:
    ld = bpy.data.lights.new("L", "POINT")
    ld.energy = energy
    lo = bpy.data.objects.new("L", ld)
    lo.location = loc
    scene.collection.objects.link(lo)

# 摄像机 - 多个角度
cam_data = bpy.data.cameras.new("C")
cam = bpy.data.objects.new("C", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam

def look_at(cam_obj, target):
    d = target - cam_obj.location
    cam_obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

# 模型尺寸
dims = obj.dimensions
print("模型尺寸:", [round(d,2) for d in dims])
radius = max(dims) * 1.8

views = {
    "front":  (0, -1, 0.2),
    "side":   (1, 0, 0.2),
    "top":    (0, 0, 1),
    "iso":    (0.8, -0.8, 0.6),
}
for name, dirv in views.items():
    dv = Vector(dirv).normalized() * radius
    cam.location = dv
    look_at(cam, Vector((0,0,0)))
    scene.render.filepath = os.path.join(OUT, f"preview_{name}.png")
    bpy.ops.render.render(write_still=True)
    print("渲染:", name)

print("RENDER_DONE")
'''
open(script, "w", encoding="utf-8").write(code)

r = subprocess.run([BLENDER, "-b", "--factory-startup", "-P", script],
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=900)
print("rc =", r.returncode)
# 打印关键输出
for line in (r.stdout or "").splitlines():
    if any(k in line for k in ["模型尺寸", "渲染", "RENDER_DONE", "Error", "error"]):
        print("  ", line)

print("\n=== 产出文件 ===")
for f in sorted(os.listdir(OUT)):
    if f.startswith("preview_"):
        p = os.path.join(OUT, f)
        print(f"  {f}  {os.path.getsize(p):,} bytes")
