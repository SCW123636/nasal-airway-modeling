# -*- coding: utf-8 -*-
r"""抽取各可用序列的真实几何仿射，验证 Δz 必须沿法向反算。

输出：控制台摘要 + work/01_inspect/affine_summary.json
用法（managed venv）：
  python.exe extract_affine.py
"""
import os, sys, json
import numpy as np
import pydicom

ROOT = r"D:\项目\鼻腔建模"
# (label, 序列目录) —— 用原始 B 块（仿射与 _clean 一致；PHI 仅文件名，不影响几何）
SERIES = [
    ("例0_Bone_0.35mm",  os.path.join(ROOT, r"资料/脱敏数据/脱敏后图像数据/ISO_Bone_0.35mm_part1/ISO_Bone_0.35mm")),
    ("患者3_t2_0.6x0.6_BONE", os.path.join(ROOT, r"资料/脱敏数据/患者ct+鼻空腔建模/患者ct+鼻空腔建模/患者3/250111559-TKT/20260217-5.___/202-0.6 x 0.6_BONE")),
    ("患者3_t1_1.0x0.5_bone", os.path.join(ROOT, r"资料/脱敏数据/患者ct+鼻空腔建模/患者ct+鼻空腔建模/患者3/250111559-TKT/20250709/202-1.0 x 0.5_bone")),
    ("患者1_1.0x0.8_Bone", os.path.join(ROOT, r"资料/脱敏数据/患者ct+鼻空腔建模/患者ct+鼻空腔建模/患者1/______-______/20260127/202-1.0 x 0.8 Bone")),
    ("患者2_Sinus0.75_H40s", os.path.join(ROOT, r"资料/脱敏数据/患者ct+鼻空腔建模/患者ct+鼻空腔建模/患者2/p01360058-____/20250902-Head^07_Sinus (Adult)/4-Sinus  0.75  H40s")),
]


def read_raw_geometry(dcm_dir):
    """从首帧读 IOP/IPP，再从全序列相邻 IPP 反算 Δz（沿法向投影）。"""
    files = [f for f in os.listdir(dcm_dir) if f.lower().endswith(".dcm")]
    recs = []
    for f in files:
        ds = pydicom.dcmread(os.path.join(dcm_dir, f), stop_before_pixels=True, force=True)
        iop = getattr(ds, "ImageOrientationPatient", None)
        ipp = getattr(ds, "ImagePositionPatient", None)
        inst = getattr(ds, "InstanceNumber", None)
        if iop is None or ipp is None or inst is None:
            continue
        recs.append((int(inst), np.array(ipp, float), np.array(iop, float)))
    recs.sort(key=lambda r: r[0])
    if len(recs) < 2:
        return None
    ipp0, iop0 = recs[0][1], recs[0][2]
    row = iop0[0:3]; col = iop0[3:6]
    normal = np.cross(row, col)
    nlen = np.linalg.norm(normal)
    normal_u = normal / nlen if nlen > 0 else normal
    # 相邻片沿法向投影差（取前 5 对平均，避免 Secondary Capture 污染）
    dzs = []
    for k in range(min(5, len(recs) - 1)):
        d = recs[k + 1][1] - recs[k][1]
        dzs.append(abs(float(np.dot(d, normal_u))))
    dz_neighbor = float(np.mean(dzs)) if dzs else 0.0
    # 全序列跨度 / (n-1)
    proj = [float(np.dot(r[1], normal_u)) for r in recs]
    dz_full = (max(proj) - min(proj)) / (len(recs) - 1) if len(recs) > 1 else 0.0
    return {
        "n_files_used": len(recs),
        "ipp_first": [round(float(x), 4) for x in ipp0],
        "iop_first": [round(float(x), 6) for x in iop0],
        "normal_unit": [round(float(x), 6) for x in normal_u],
        "dz_from_neighbor_ipp": round(dz_neighbor, 4),
        "dz_from_full_span": round(dz_full, 4),
    }


def main():
    sys.path.insert(0, os.path.join(ROOT, "work/lib"))
    from dicom_sitk import load_series_sitk
    out = []
    for label, d in SERIES:
        print("\n" + "=" * 70)
        print("SERIES:", label)
        try:
            vol, sp, org, meta = load_series_sitk(d, verbose=True)
            raw = read_raw_geometry(d)
            rec = {"label": label, "path": d,
                   "itk_spacing_xyz": [round(float(x), 4) for x in sp],
                   "itk_origin_xyz": [round(float(x), 4) for x in org],
                   "tag_slice_thickness": meta["slice_thickness"],
                   "tag_spacing_between": meta["spacing_between"],
                   "rescale_intercept": meta["rescale_intercept"],
                   "series_instance_uid": getattr(__import__("pydicom"), "dcmread", None) and None,
                   "hu_range": list(meta["hu_range"]),
                   "raw": raw}
            # 取 SeriesInstanceUID / Manufacturer / InstitutionName
            import pydicom as pd
            f0 = sorted([f for f in os.listdir(d) if f.lower().endswith(".dcm")])[0]
            ds = pd.dcmread(os.path.join(d, f0), stop_before_pixels=True, force=True)
            rec["series_instance_uid"] = str(getattr(ds, "SeriesInstanceUID", ""))
            rec["manufacturer"] = str(getattr(ds, "Manufacturer", ""))
            rec["institution"] = str(getattr(ds, "InstitutionName", ""))
            rec["modality"] = meta["modality"]
            rec["convolution_kernel"] = meta["convolution_kernel"]
            out.append(rec)
            # 打印三方对照
            if raw:
                print(f"  ITK Δz           = {rec['itk_spacing_xyz'][2]} mm")
                print(f"  SliceThickness标签= {rec['tag_slice_thickness']} mm")
                print(f"  相邻IPP反算 Δz   = {raw['dz_from_neighbor_ipp']} mm")
                print(f"  全跨度反算 Δz    = {raw['dz_from_full_span']} mm")
                print(f"  RescaleIntercept = {rec['rescale_intercept']}")
                print(f"  SeriesUID        = {rec['series_instance_uid']}")
        except Exception as e:
            print("  ERROR:", repr(e))
            out.append({"label": label, "path": d, "error": repr(e)})
    with open(os.path.join(ROOT, "work/01_inspect/affine_summary.json"), "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=2)
    print("\n[done] -> work/01_inspect/affine_summary.json")


if __name__ == "__main__":
    main()
