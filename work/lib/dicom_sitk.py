# -*- coding: utf-8 -*-
"""用 SimpleITK 读 DICOM 序列（可解 JPEG Lossless Process 14）。

为什么不用 nasal_io.load_dicom_series：
  - 本批数据多为压缩传输语法（1.2.840.10008.1.2.4.70 JPEG Lossless），
    pydicom 缺 gdcm/pylibjpeg 插件 → 解码失败。
  - SimpleITK 内置 ITK/GDCM 解码栈，实测可直接读，且能同时给出
    spacing/origin（从 ImagePositionPatient 反算，比手写更可靠）。

返回与 nasal_io 一致的 (vol_zyx, spacing_xyz, origin_xyz, meta)。
"""
import os
import numpy as np
import SimpleITK as sitk


def load_series_sitk(dcm_dir, verbose=False):
    if not os.path.isdir(dcm_dir):
        raise FileNotFoundError(dcm_dir)
    r = sitk.ImageSeriesReader()
    names = r.GetGDCMSeriesFileNames(dcm_dir)
    if not names:
        raise FileNotFoundError("SimpleITK 未找到序列: " + dcm_dir)
    r.SetFileNames(names)
    img = r.Execute()

    vol = sitk.GetArrayFromImage(img)            # (z, y, x)
    sx, sy, sz = img.GetSpacing()                # (x, y, z) mm
    org = img.GetOrigin()                        # (x, y, z) mm

    # 元数据：从首帧读。扩展名大小写不可靠（同一批数据里 .dcm 与 .DCM 都出现过），
    # 只按大小写不敏感匹配，否则 sorted(...)[0] 会越界。
    import pydicom
    files = sorted(f for f in os.listdir(dcm_dir) if f.lower().endswith('.dcm'))
    if not files:
        files = sorted(str(f) for f in names)
    f0 = files[0]
    ds = pydicom.dcmread(os.path.join(dcm_dir, f0), stop_before_pixels=True, force=True)
    meta = {
        "n_slices": int(vol.shape[0]),
        "rows": int(vol.shape[1]), "cols": int(vol.shape[2]),
        "spacing_xyz": (float(sx), float(sy), float(sz)),
        "origin_xyz": tuple(float(v) for v in org),
        "hu_range": (int(vol.min()), int(vol.max())),
        "series_description": str(getattr(ds, "SeriesDescription", "")),
        "modality": str(getattr(ds, "Modality", "")),
        "slice_thickness": float(getattr(ds, "SliceThickness", 0) or 0),
        "spacing_between": float(getattr(ds, "SpacingBetweenSlices", 0) or 0),
        "convolution_kernel": str(getattr(ds, "ConvolutionKernel", "")),
        "kvp": str(getattr(ds, "KVP", "")),
        "transfer_syntax": str(getattr(ds.file_meta, "TransferSyntaxUID", "")),
        "rescale_intercept": float(getattr(ds, "RescaleIntercept", 0) or 0),
        "rescale_slope": float(getattr(ds, "RescaleSlope", 1) or 1),
        "patient_position": str(getattr(ds, "PatientPosition", "")),
        "n_files": len(names),
    }
    if verbose:
        print(f"[sitk] {os.path.basename(dcm_dir)}  {vol.shape}  spacing {meta['spacing_xyz']}")
    return vol, meta["spacing_xyz"], meta["origin_xyz"], meta


if __name__ == "__main__":
    import sys, json
    d = sys.argv[1]
    v, sp, org, m = load_series_sitk(d, verbose=True)
    print(json.dumps(m, ensure_ascii=False, indent=2, default=str))
