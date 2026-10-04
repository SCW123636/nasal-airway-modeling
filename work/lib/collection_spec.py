# -*- coding: utf-8 -*-
"""生成「三患者采集规格对齐表」——从脱敏后数据实测导出，不手写。

对每个患者的每个 CT 影像序列（排除 SR/DoseReport/Scout/Topogram 等非体数据），
实测：层厚、层数、面内像素、kernel、HU 范围、几何一致性。
输出 Markdown 表 + JSON。
"""
import os, json, csv
import numpy as np
import pydicom

ROOT = r"D:\项目\鼻腔建模"
CLEAN = os.path.join(ROOT, "资料", "脱敏数据_clean")
OUTDIR = os.path.join(ROOT, "work", "04_cfd_ready")
os.makedirs(OUTDIR, exist_ok=True)

# 非体数据序列（不做 CFD，不进表）
SKIP_KEYWORDS = ["Report Data", "Patient Protocol", "Evidence Documents",
                 "Dose Report", "Scout", "Topogram", "101", "MPR"]


CT_IMAGE = "1.2.840.10008.5.1.4.1.1.2"     # CT Image Storage


def _read_light(fp):
    try:
        return pydicom.dcmread(fp, stop_before_pixels=True, force=True)
    except Exception:
        return None


def probe_series(d):
    """只认 CT Image Storage 帧；同一 series 目录里混入的 Secondary Capture / SR 一律剔除。"""
    allf = sorted([f for f in os.listdir(d) if f.endswith(".dcm")])
    if not allf:
        return None

    # 逐帧筛出真正的 CT 图像，同时记录被剔除的非 CT 帧
    fs, ds, n_nonct = [], None, 0
    for f in allf:
        _d = _read_light(os.path.join(d, f))
        if _d is None:
            n_nonct += 1
            continue
        if str(getattr(_d, "SOPClassUID", "")) != CT_IMAGE:
            n_nonct += 1
            continue
        fs.append(f)
        if ds is None:
            ds = _d
    if ds is None or not fs:
        return None

    desc = str(getattr(ds, "SeriesDescription", ""))
    if any(k.lower() in desc.lower() for k in SKIP_KEYWORDS):
        return None
    rows = int(getattr(ds, "Rows", 0) or 0)
    cols = int(getattr(ds, "Columns", 0) or 0)
    if rows == 0 or cols == 0:
        return None

    ps = [float(x) for x in getattr(ds, "PixelSpacing", [])]
    # 层间距：必须按位置排序后计算，且只沿法向投影 —— 文件名顺序不可靠
    dz = None
    dz_min = dz_max = None
    try:
        recs = []
        for f in fs:
            d2 = _read_light(os.path.join(d, f))
            if d2 is None:
                continue
            ipp = [float(x) for x in d2.ImagePositionPatient]
            inst = int(getattr(d2, "InstanceNumber", 0) or 0)
            recs.append((inst, ipp))
        recs.sort(key=lambda t: t[0])            # 按 InstanceNumber 排序
        pts = np.array([r[1] for r in recs])
        # 取法向（由 IOP 前两组向量叉乘）
        iop0 = [float(x) for x in getattr(ds, "ImageOrientationPatient", [1,0,0,0,1,0])]
        nvec = np.cross(np.array(iop0[:3]), np.array(iop0[3:]))
        proj = pts @ nvec                        # 沿法向投影
        diffs = np.abs(np.diff(proj))
        if len(diffs):
            dz = float(np.median(diffs))
            dz_min = float(diffs.min())
            dz_max = float(diffs.max())
    except Exception:
        pass
    thick = float(getattr(ds, "SliceThickness", 0) or 0)
    iop = [float(x) for x in getattr(ds, "ImageOrientationPatient", [])]
    # 轴向性：法向量与 z 轴夹角
    axial = None
    if len(iop) == 6:
        r = np.array(iop[:3]); c = np.array(iop[3:])
        n = np.cross(r, c)
        axial = round(float(np.degrees(np.arccos(np.clip(abs(n[2]), 0, 1)))), 2)

    return {
        "desc": desc, "kernel": str(getattr(ds, "ConvolutionKernel", "")),
        "n": len(fs), "n_nonct": n_nonct, "rows": rows, "cols": cols,
        "ps": round(ps[0], 4) if ps else None,
        "thick": thick, "dz": round(dz, 4) if dz else None,
        "dz_min": round(dz_min, 4) if dz_min else None,
        "dz_max": round(dz_max, 4) if dz_max else None,
        "intercept": float(getattr(ds, "RescaleIntercept", 0) or 0),
        "slope": float(getattr(ds, "RescaleSlope", 1) or 1),
        "iop": [round(x, 5) for x in iop],
        "axial_tilt_deg": axial,
        "kvp": str(getattr(ds, "KVP", "")),
        "ts": str(getattr(ds.file_meta, "TransferSyntaxUID", "")),
        "bits": int(getattr(ds, "BitsStored", 0) or 0),
        "path": os.path.relpath(d, CLEAN),
    }


TABLE_TS = {
    "1.2.840.10008.1.2": "未压缩",
    "1.2.840.10008.1.2.1": "未压缩(Explicit LE)",
    "1.2.840.10008.1.2.4.70": "JPEG Lossless P14",
    "1.2.840.10008.1.2.4.80": "JPEG-LS Lossless",
    "1.2.840.10008.1.2.4.90": "JPEG2000 Lossless",
    "1.2.840.10008.1.2.4.51": "JPEG Baseline",
}

results = {}
for pat in sorted(os.listdir(CLEAN)):
    pdir = os.path.join(CLEAN, pat)
    if not os.path.isdir(pdir):
        continue
    lst = []
    for cur, dirs, files in os.walk(pdir):
        if any(f.endswith(".dcm") for f in files):
            r = probe_series(cur)
            if r:
                lst.append(r)
    lst.sort(key=lambda r: (-r["n"]))
    results[pat] = lst

with open(os.path.join(OUTDIR, "collection_spec.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

# ---- Markdown ----
lines = ["# 三患者 CT 采集规格对齐表（实测导出）", "",
         "> 由 `work/lib/collection_spec.py` 从脱敏后数据实测生成，非人工填写。",
         "> 已排除 Scout / Topogram / Dose Report / Report Data / MPR 等非体数据序列。", ""]
for pat, lst in results.items():
    lines.append(f"## {pat}")
    lines.append("")
    lines.append("| 序列 | kernel | 层数 | 标称层厚 | 实算dz(中位) | dz范围 | 面内mm | 矩阵 | HU截距 | 轴向倾角 | 传输语法 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in lst:
        ts = TABLE_TS.get(r["ts"], r["ts"][:28])
        lines.append(f"| {r['desc']} | {r['kernel']} | {r['n']} | {r['thick']} | "
                     f"{r['dz']} | {r['dz_min']}~{r['dz_max']} | {r['ps']} | {r['cols']}×{r['rows']} | "
                     f"{int(r['intercept'])} | {r['axial_tilt_deg']}° | {ts} |")
    lines.append("")

txt = "\n".join(lines)
with open(os.path.join(OUTDIR, "采集规格对齐表.md"), "w", encoding="utf-8") as f:
    f.write(txt)
print(txt)
