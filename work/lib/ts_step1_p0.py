# -*- coding: utf-8 -*-
"""
step1-p0：例0（0.35mm ISO 真各向同性，A 块）Bone 序列 3 个 part -> 单一 NIfTI。
part 结构：资料\脱敏数据\脱敏后图像数据\ISO_Bone_0.35mm_part{1,2,3}\ISO_Bone_0.35mm\*.dcm
拼接排序：按 IPP[2]（z）全局排序 —— probe_iso035_merge 已验证 dz 唯一值 {0.35}、单调。
输出：C:\ts_work\p0\ct.nii.gz（ASCII 路径，避开 ITK 非 ASCII 路径坑）
用 Slicer 自带 PythonSlicer 跑（有 SimpleITK/GDCM）。
"""
import os, sys, json
import SimpleITK as sitk

ISO = r"D:\项目\鼻腔建模\资料\脱敏数据\脱敏后图像数据"
SERIES = "ISO_Bone_0.35mm"
OUT_NII = r"C:\ts_work\p0\ct.nii.gz"
OUT_JSON = r"C:\ts_work\p0\step1_p0.json"

files = []
for i in (1, 2, 3):
    d = os.path.join(ISO, f"{SERIES}_part{i}", SERIES)
    for f in sorted(os.listdir(d)):
        if f.lower().endswith(".dcm"):
            files.append(os.path.join(d, f))

rep = {"n_files": len(files)}
if not files:
    rep["ok"] = False
else:
    # 用 z（IPP[2]）全局排序：三 part 拼接后 dz 唯一 0.35、单调，z 排序即正确层序
    zmap = {}
    for fp in files:
        r = sitk.ImageFileReader()
        r.SetFileName(fp)
        r.ReadImageInformation()
        zmap[fp] = r.GetOrigin()[2]
    files_sorted = sorted(files, key=lambda fp: zmap[fp])
    zs = [zmap[fp] for fp in files_sorted]
    dzs = [round(zs[k+1] - zs[k], 4) for k in range(len(zs) - 1)]

    r = sitk.ImageSeriesReader()
    r.SetFileNames(files_sorted)
    img = r.Execute()
    os.makedirs(os.path.dirname(OUT_NII), exist_ok=True)
    sitk.WriteImage(img, OUT_NII)
    rep.update({
        "ok": True,
        "size_xyz": list(img.GetSize()),
        "spacing_xyz": [round(v, 6) for v in img.GetSpacing()],
        "origin_xyz": [round(v, 3) for v in img.GetOrigin()],
        "direction": [round(v, 5) for v in img.GetDirection()],
        "pixel_type": str(img.GetPixelIDTypeAsString()),
        "z_first": round(zs[0], 3), "z_last": round(zs[-1], 3),
        "z_span_mm": round(abs(zs[-1] - zs[0]), 3),
        "dz_unique_sorted": sorted(set(dzs))[:6],
        "dz_abs_max": round(max(abs(d) for d in dzs), 4),
        "nii_bytes": os.path.getsize(OUT_NII),
    })

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=2)
print(json.dumps(rep, ensure_ascii=False, indent=2))
