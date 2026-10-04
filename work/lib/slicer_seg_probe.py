# -*- coding: utf-8 -*-
"""
Slicer 端分割探针 (step 1)
目的：不预设结论，先回答三个诊断问题
  Q1  阈值 -1024~-300 HU 提取出的空气，连通分量有多少个？各自体积？
  Q2  最大连通体到底是「鼻腔主气道」还是「外部空气」？
  Q3  在鼻孔平面 z=?? 处切断后，鼻腔能不能独立成一个连通体？

输出：纯 JSON，避免依赖 Slicer 控制台输出（本机 stdout 不可靠）
"""
import os, json, sys
import numpy as np
import slicer
import SimpleITK as sitk
from scipy import ndimage

OUT = r"C:\nasal_probe"
os.makedirs(OUT, exist_ok=True)
REPORT = os.path.join(OUT, "slicer_probe.json")

report = {"steps": [], "ok": False}


def log(msg):
    report["steps"].append(str(msg))


try:
    # ---------- 1. 读 DICOM ----------
    dcm_dir = r"D:\项目\鼻腔建模\work\00_dicom\bone"
    log(f"dcm_dir={dcm_dir} exists={os.path.isdir(dcm_dir)}")

    # Slicer 的 DICOM 索引器是异步的，这里改用 SimpleITK 直读（已在上一轮验证可行）
    reader = sitk.ImageSeriesReader()
    names = reader.GetGDCMSeriesFileNames(dcm_dir)
    log(f"series files={len(names)}")
    reader.SetFileNames(names)
    img = reader.Execute()
    arr = sitk.GetArrayFromImage(img)          # (z, y, x) int16 HU
    sp = img.GetSpacing()                      # (x, y, z)
    org = img.GetOrigin()
    log(f"shape={arr.shape} spacing={sp} origin={org}")
    log(f"HU range=({int(arr.min())}, {int(arr.max())})")

    np.save(os.path.join(OUT, "vol_zyx.npy"), arr)

    # ---------- 2. 阈值提取空气 ----------
    air = (arr < -300) & (arr > -1100)
    log(f"air voxels={int(air.sum())}  ({air.mean()*100:.2f}%)")
    np.save(os.path.join(OUT, "air_mask.npy"), air)

    # ---------- 3. 连通分量分析 ----------
    lab, n = ndimage.label(air)
    log(f"n_components={n}")
    sizes = ndimage.sum(air, lab, range(1, n + 1)).astype(np.int64)
    order = np.argsort(sizes)[::-1][:12]
    top = []
    for i in order:
        lb = int(i + 1)
        idx = np.where(lab == lb)
        zr = [int(idx[0].min()), int(idx[0].max())]
        yr = [int(idx[1].min()), int(idx[1].max())]
        xr = [int(idx[2].min()), int(idx[2].max())]
        # 这个分量与图像边界的接触量（外部空气必然接触边界）
        touch = int((zr[0] == 0) + (zr[1] == arr.shape[0] - 1) +
                    (yr[0] == 0) + (yr[1] == arr.shape[1] - 1) +
                    (xr[0] == 0) + (xr[1] == arr.shape[2] - 1))
        top.append({
            "label": lb,
            "size": int(sizes[i]),
            "z": zr, "y": yr, "x": xr,
            "bbox_touch_image_border_faces": touch,
            "centroid_z": round(float(idx[0].mean()), 1),
            "centroid_y": round(float(idx[1].mean()), 1),
            "centroid_x": round(float(idx[2].mean()), 1),
        })
    report["top_components"] = top
    log(f"top components: {json.dumps(top[:6], ensure_ascii=False)}")

    report["ok"] = True

except Exception as e:
    import traceback
    report["error"] = str(e)
    report["traceback"] = traceback.format_exc()

with open(REPORT, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print("PROBE DONE ->", REPORT)
