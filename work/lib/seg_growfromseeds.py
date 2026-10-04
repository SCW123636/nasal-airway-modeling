# -*- coding: utf-8 -*-
"""专家在环分割的脚本化兜底实现（Grow from Seeds，第一遍）。
对应 `work/分割流程规范.md` 步骤 1-2 的自动化骨架 + 步骤 5 的部分 QC。

为什么是兜底：TotalSegmentator step2 权重仍被代理断连、零掩膜，故按规范
"TS 权重失败 → Slicer 人工种子 + Grow from Seeds" 落一个可复现的脚本版：
  - 自动提出左/右鼻腔 + 鼻咽 3 类种子（基于空气连通域几何启发，需人工确认）
  - 在 HU<-300 空气候选区内做区域生长（保留含种子的连通域）
  - 跑新验收条件的 QC：HU 纯净度 / 连续性 / bbox / 体积
  - 明确标注：口腔/鼻窦屏障尚未施加，泄漏需 Slicer 人工复核

输入：例0 (0.35mm 真各向同性，最干净，作方法学锚点)
输出：work/02_seg/ 下 initial 标签 NRRD + 种子 JSON + manifest 草稿

用法（managed venv）：
  C:/Users/lenovo/.workbuddy/binaries/python/envs/default/Scripts/python.exe seg_growfromseeds.py
"""
import os, sys, json, glob
import numpy as np
import SimpleITK as sitk

ROOT = r"D:/项目/鼻腔建模"
BASE = os.path.join(ROOT, r"资料/脱敏数据/脱敏后图像数据")
SERIES_PARTS = [os.path.join(BASE, f"ISO_Bone_0.35mm_part{i}/ISO_Bone_0.35mm") for i in (1, 2, 3)]
OUTDIR = os.path.join(ROOT, r"work/02_seg")
HU_AIR = -300  # 空气候选阈值（主结果 T300）


def load_full_series(part_dirs):
    """收集各 part 嵌套目录里的 .dcm，按 InstanceNumber 排序后加载完整体积。
    处理例0 拆成 3 个 part 的情况（part 直接挂在 脱敏后图像数据/ 下）。"""
    import pydicom
    files = []
    for d in part_dirs:
        for f in os.listdir(d):
            if f.lower().endswith(".dcm"):
                files.append(os.path.join(d, f))
    if not files:
        raise FileNotFoundError("未找到 dcm: " + str(part_dirs))
    # 按 InstanceNumber 排序
    def inst(fn):
        try:
            return int(pydicom.dcmread(fn, stop_before_pixels=True, force=True).InstanceNumber or 0)
        except Exception:
            return 0
    files.sort(key=inst)
    r = sitk.ImageSeriesReader()
    r.SetFileNames(files)
    img = r.Execute()
    vol = sitk.GetArrayFromImage(img)            # (z,y,x)
    sx, sy, sz = img.GetSpacing()
    org = img.GetOrigin()
    return vol, (float(sx), float(sy), float(sz)), tuple(float(v) for v in org), img, files


def propose_seeds(vol, air):
    """基于空气连通域几何，提出左/右鼻腔 + 鼻咽 种子（index 坐标 zi,yi,xi）。
    纯启发式，需人工确认；返回 dict + 每类命中状态。"""
    # 头部 bbox（用软组织/骨 HU>0 估计）
    tissue = vol > 0
    zt, yt, xt = np.where(tissue)
    zmin, zmax = zt.min(), zt.max()
    ymin, ymax = yt.min(), yt.max()  # LPS +Y=后，ymin=前(鼻腔在前)
    xmin, xmax = xt.min(), xt.max()
    zr, yr, xr = zmax - zmin, ymax - ymin, xmax - xmin
    mid_x = (xmin + xmax) // 2

    def snap(zi, yi, xi, R=6):
        zi = int(np.clip(zi, 0, air.shape[0] - 1))
        yi = int(np.clip(yi, 0, air.shape[1] - 1))
        xi = int(np.clip(xi, 0, air.shape[2] - 1))
        if air[zi, yi, xi]:
            return (zi, yi, xi), True
        zz, yy, xx = np.where(air[max(0,zi-R):zi+R+1, max(0,yi-R):yi+R+1, max(0,xi-R):xi+R+1])
        if len(zz) == 0:
            return (zi, yi, xi), False
        # 取距中心最近
        d = (zz - (zi - max(0,zi-R)))**2 + (yy - (yi - max(0,yi-R)))**2 + (xx - (xi - max(0,xi-R)))**2
        k = d.argmin()
        return (int(max(0,zi-R)+zz[k]), int(max(0,yi-R)+yy[k]), int(max(0,xi-R)+xx[k])), True

    seeds = {}
    # 鼻腔：前 1/3、z 中段偏上、中线两侧
    z_n = zmin + int(0.55 * zr)
    y_n = ymin + int(0.30 * yr)
    l = snap(z_n, y_n, mid_x + int(0.12 * xr))
    r = snap(z_n, y_n, mid_x - int(0.12 * xr))
    # 鼻咽：后 1/8、z 偏上
    z_np = zmin + int(0.72 * zr)
    y_np = ymax - int(0.10 * yr)
    np_ = snap(z_np, y_np, mid_x)
    seeds["nasal_L"] = {"voxel": list(l[0]), "hit": l[1]}
    seeds["nasal_R"] = {"voxel": list(r[0]), "hit": r[1]}
    seeds["nasopharynx"] = {"voxel": list(np_[0]), "hit": np_[1]}
    return seeds, {"zmin": int(zmin), "zmax": int(zmax), "ymin": int(ymin), "ymax": int(ymax),
                   "xmin": int(xmin), "xmax": int(xmax), "mid_x": int(mid_x)}


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    print("[1/6] 加载完整体积 (合并 3 part) ...")
    vol, spacing, origin, img, files = load_full_series(SERIES_PARTS)
    print(f"     shape={vol.shape} spacing={spacing} origin={origin} n_files={len(files)}")

    print("[2/6] 空气候选 HU<{} ...".format(HU_AIR))
    air = vol < HU_AIR
    print(f"     空气体素数={int(air.sum())}  占比={air.mean()*100:.2f}%")

    print("[3/6] 提出种子 ...")
    seeds, bbox = propose_seeds(vol, air)
    for k, v in seeds.items():
        print(f"     {k}: voxel={v['voxel']} hit={v['hit']}")

    print("[4/6] 连通域 + 区域生长 (保留含种子的连通域) ...")
    air_sitk = sitk.GetImageFromArray(air.astype(np.uint8))
    air_sitk.SetSpacing(spacing); air_sitk.SetOrigin(origin)
    cc = sitk.ConnectedComponent(air_sitk)
    lbl = sitk.GetArrayFromImage(cc)  # (z,y,x)
    n_labels = int(lbl.max())
    # 含种子的标签集合
    keep = set()
    for k, v in seeds.items():
        if v["hit"]:
            zi, yi, xi = v["voxel"]
            keep.add(int(lbl[zi, yi, xi]))
    keep.discard(0)
    mask = np.isin(lbl, list(keep)) if keep else np.zeros_like(air, dtype=bool)
    print(f"     总连通域={n_labels}  含种子保留={len(keep)}")

    print("[5/6] QC (新验收条件子集) ...")
    n_mask = int(mask.sum())
    hu_pos = int((vol[mask] > 0).sum()) if n_mask else 0
    purity = 1.0 - (hu_pos / n_mask) if n_mask else 0.0
    zt, yt, xt = np.where(mask)
    bb = {"z": [int(zt.min()), int(zt.max())], "y": [int(yt.min()), int(yt.max())],
          "x": [int(xt.min()), int(xt.max())]}
    bb_mm = {"x": (bb["x"][1]-bb["x"][0])*spacing[0], "y": (bb["y"][1]-bb["y"][0])*spacing[1],
             "z": (bb["z"][1]-bb["z"][0])*spacing[2]}
    vol_mm3 = n_mask * spacing[0] * spacing[1] * spacing[2]
    # 残留连通域数
    cc2 = sitk.ConnectedComponent(sitk.GetImageFromArray(mask.astype(np.uint8)))
    lbl2 = sitk.GetArrayFromImage(cc2)
    n_comp = int(lbl2.max())
    # 诚实 QC：鼻腔+鼻窦合理体积通常 < ~100 cm³；远超即口腔/鼻窦未分离
    oral_leak = (vol_mm3 / 1000.0) > 100.0
    print(f"     体素={n_mask} 体积={vol_mm3/1000:.1f} cm^3")
    print(f"     [QC] 口腔/鼻窦泄漏={ 'FAIL(须人工屏障)' if oral_leak else 'PASS' }")
    print(f"     HU纯净度={purity*100:.2f}% (标签内HU>0体素={hu_pos})")
    print(f"     残留连通域={n_comp}  bbox(mm)={ {k: round(v,2) for k,v in bb_mm.items()} }")

    print("[6/6] 写出 NRRD + 种子 + manifest ...")
    out_img = sitk.GetImageFromArray(mask.astype(np.uint8))
    out_img.SetSpacing(spacing); out_img.SetOrigin(origin)
    nrrd = os.path.join(OUTDIR, "case0_main_nasal_airway_initial.nrrd")
    # ITK NRRD writer 无法 fopen 中文路径 -> 先写 ASCII 临时目录再 shutil.move
    import shutil
    tmp = r"C:/tmp_nasal/case0_main_nasal_airway_initial.nrrd"
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    sitk.WriteImage(out_img, tmp)
    shutil.move(tmp, nrrd)
    with open(os.path.join(OUTDIR, "case0_seeds.json"), "w", encoding="utf-8") as f:
        json.dump({"seeds": seeds, "bbox_index": bbox, "hu_air": HU_AIR,
                   "note": "自动提出，需人工确认；口腔/鼻窦屏障未施加"}, f, ensure_ascii=False, indent=2)
    manifest = {
        "case": "例0", "series": "ISO_Bone_0.35mm", "threshold_HU": HU_AIR,
        "spacing_mm": spacing, "origin_mm": origin, "units": "mm", "coord": "LPS",
        "method": "Grow-from-Seeds fallback (TS权重未下载)",
        "seeds": seeds,         "qc": {"voxels": n_mask, "volume_cm3": round(vol_mm3/1000, 2),
                  "hu_purity": round(purity, 4), "n_components": n_comp, "bbox_mm": bb_mm,
                  "oral_leak_suspected": bool(oral_leak)},
        "warning": "口腔/鼻窦屏障未施加；oral/sinus 泄漏需 Slicer 人工复核 (规范 step3-4)",
        "opening_status_list": {"maxillary_sinus": "unknown", "frontal_sinus": "unknown",
                                "ethmoid_sinus": "unknown", "sphenoid_sinus": "unknown",
                                "nostril_L": "open(待确认)", "nostril_R": "open(待确认)",
                                "nasopharynx_outlet": "open(待确认)"}
    }
    with open(os.path.join(OUTDIR, "case0_manifest_initial.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # self-check（ITK 读写均不支持中文路径，已用 ASCII 临时写+move 绕过，故回读改用 os.path）
    assert os.path.exists(nrrd), "NRRD 未写出"
    assert os.path.getsize(nrrd) > 1000, "NRRD 过小"
    assert n_mask > 1000, "掩膜过小，种子可能全 miss"
    assert purity >= 0.999, f"HU纯净度过低 {purity}"
    print("self_check: PASS")
    print("DONE ->", OUTDIR)


if __name__ == "__main__":
    main()
