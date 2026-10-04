# -*- coding: utf-8 -*-
"""step1：三例 DICOM -> NIfTI（保留 geometry）。用 Slicer 的 SimpleITK 跑。"""
import os
import json
import SimpleITK as sitk

ROOT = r"D:\项目\鼻腔建模"
# ★ 坑：ITK 的 NIfTI writer 用 fopen，不支持非 ASCII 路径（中文路径会报
#   "cannot open output file"）。所以中间产物一律走纯 ASCII 工作目录，
#   处理完再用 Python 的 shutil 拷回项目目录（Python 侧支持中文路径）。
OUTBASE = r"C:\ts_work"
PATIENTS = {
    "p1": os.path.join(ROOT, r"资料\脱敏数据_clean\患者1\______-______\20260127\202-1.0 x 0.8 Bone"),
    "p2": os.path.join(ROOT, r"资料\脱敏数据_clean\患者2\p01360058-____\20250902-Head^07_Sinus (Adult)\4-Sinus  0.75  H40s"),
    "p3": os.path.join(ROOT, r"资料\脱敏数据_clean\患者3\250111559-TKT\20260217-5.___\202-0.6 x 0.6_BONE"),
}

rep = {}
for k, d in PATIENTS.items():
    e = {"dcm_dir": d, "exists": os.path.isdir(d)}
    if not e["exists"]:
        rep[k] = e
        continue
    try:
        r = sitk.ImageSeriesReader()
        names = r.GetGDCMSeriesFileNames(d)
        e["n_files"] = len(names)
        if not names:
            e["ok"] = False
            e["why"] = "no series"
            rep[k] = e
            continue
        r.SetFileNames(names)
        img = r.Execute()
        pdir = os.path.join(OUTBASE, k)
        os.makedirs(pdir, exist_ok=True)
        nii = os.path.join(pdir, "ct.nii.gz")
        sitk.WriteImage(img, nii)
        e.update({
            "ok": True, "nii": nii,
            "size_xyz": list(img.GetSize()),
            "spacing_xyz": [round(v, 5) for v in img.GetSpacing()],
            "origin_xyz": [round(v, 3) for v in img.GetOrigin()],
            "direction": [round(v, 3) for v in img.GetDirection()],
            "pixel_type": str(img.GetPixelIDTypeAsString()),
            "nii_bytes": os.path.getsize(nii),
        })
    except Exception as ex:
        e["ok"] = False
        e["why"] = f"{type(ex).__name__}: {ex}"
    rep[k] = e

with open(os.path.join(OUTBASE, "step1_convert.json"), "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=2)
print(json.dumps(rep, ensure_ascii=False, indent=2))
