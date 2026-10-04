# -*- coding: utf-8 -*-
"""Blender 渲染鼻腔模型 — 提高亮度，看清拓扑"""
import os, subprocess

OUT = r"D:\项目\鼻腔建模\work\03_mesh"
BLENDER = r"D:\项目\鼻腔建模\软件\blender\blender.exe"

script = os.path.join(OUT, "_blender_render2.py")
code = r'''# -*- coding: utf-8 -*-
import bpy, os
from mathutils import Vector

OUT = r"D:\项目\鼻腔建模\work\03_mesh"
MESH = os.path.join(OUT, "airway_smooth2.stl")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath=MESH)
obj = [o for o in bpy.data.objects if o.type == "MESH"][0]
bpy.context.view_layer.update()

bbox = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
center = sum(bbox, Vector((0,0,0))) / 8
obj.location -= center
bpy.context.view_layer.update()

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 1200
scene.render.resolution_y = 900
scene.render.film_transparent = False
# EEVEE 亮度设置
scene.view_settings.exposure = 0.8
scene.view_settings.look = "None"

scene.world = bpy.data.worlds.new("W")
scene.world.use_nodes = True
bgn = scene.world.node_tree.nodes["Background"]
bgn.inputs[0].default_value = (0.12, 0.14, 0.18, 1)
bgn.inputs[1].default_value = 1.5

mat = bpy.data.materials.new("M")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.90, 0.55, 0.50, 1)
bsdf.inputs["Metallic"].default_value = 0.15
bsdf.inputs["Roughness"].default_value = 0.55
obj.data.materials.append(mat)

# 更强的多向光
for loc, energy in [((8, -8, 8), 6000), ((-8, -6, 6), 4000),
                    ((0, 10, 6), 3000), ((0, -10, -4), 2000)]:
    ld = bpy.data.lights.new("L", "POINT")
    ld.energy = energy
    ld.shadow_soft_size = 3.0
    lo = bpy.data.objects.new("L", ld)
    lo.location = loc
    scene.collection.objects.link(lo)

# 用 SUN 光补充
sd = bpy.data.lights.new("S", "SUN")
sd.energy = 3.0
so = bpy.data.objects.new("S", sd)
so.rotation_euler = (0.6, 0.2, 0.8)
scene.collection.objects.link(so)

cam_data = bpy.data.cameras.new("C")
cam = bpy.data.objects.new("C", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam

def look_at(c, t):
    d = t - c.location
    c.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

dims = obj.dimensions
radius = max(dims) * 1.7

for name, dirv in {
    "front": (0, -1, 0.1), "side": (1, 0.1, 0.1),
    "top": (0.05, 0, 1), "iso": (0.8, -0.7, 0.5),
}.items():
    cam.location = Vector(dirv).normalized() * radius
    look_at(cam, Vector((0,0,0)))
    scene.render.filepath = os.path.join(OUT, f"preview2_{name}.png")
    bpy.ops.render.render(write_still=True)

print("DONE")
'''
open(script, "w", encoding="utf-8").write(code)

r = subprocess.run([BLENDER, "-b", "--factory-startup", "-P", script],
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=900)
print("rc =", r.returncode)
for line in (r.stdout or "").splitlines():
    if any(k in line for k in ["DONE", "Error", "Saved"]):
        print("  ", line)
print("\n=== 产出 ===")
for f in sorted(os.listdir(OUT)):
    if f.startswith("preview2_"):
        print(f"  {f}  {os.path.getsize(os.path.join(OUT,f)):,}")
