# -*- coding: utf-8 -*-
"""
鼻腔气道自动分割 v2 — 基于实测解剖结构
====================================================
本病例实测解剖（z=170, y=150 剖面）：
  x≈189-197  左鼻腔
  x≈197-213  鼻中隔（组织+骨）
  x≈214-227  右鼻腔
  x≈227-245  右侧鼻甲/骨壁
  x≈245-258  右上颌窦（独立腔，需排除）

核心策略：
  1. 阈值提取空气
  2. **切断鼻孔平面**（外部空气与鼻腔的界面）
  3. 从鼻腔内部种子点做 3D 区域生长（限制在鼻腔解剖范围内）
  4. 排除鼻窦：不在生长范围内的自动被排除
"""
import os
import numpy as np
from scipy import ndimage


def segment_nasal_airway_v2(vol, spacing, params=None, verbose=True):
    """
    参数（全部显式可调）
    """
    P = {
        "hu_air_max": -300,
        # 鼻腔解剖 x 范围（从剖面实测：189~227，留余量）
        "nasal_x_min": 170,
        "nasal_x_max": 250,
        # 鼻腔 z 范围（从骨骼密度：鼻腔主体 130~240，向下延到鼻咽 300）
        "nasal_z_min": 60,
        "nasal_z_max": 320,
        # 鼻孔切断：y 小于此值视为外部
        "nostril_y_cut": 40,
        # 最小连通域
        "min_size": 200,
    }
    if params:
        P.update(params)

    nz, ny, nx = vol.shape
    diag = {}

    # ---------- 1. 空气掩膜 ----------
    air = vol < P["hu_air_max"]
    diag["air_total"] = int(air.sum())

    # ---------- 2. 限定解剖工作区（ROI） ----------
    roi = np.zeros_like(air)
    roi[P["nasal_z_min"]:P["nasal_z_max"],
        P["nostril_y_cut"]:,
        P["nasal_x_min"]:P["nasal_x_max"]] = True
    air_roi = air & roi
    diag["air_in_roi"] = int(air_roi.sum())

    # ---------- 3. 3D 连通域 ----------
    lbl, n = ndimage.label(air_roi, structure=np.ones((3, 3, 3)))
    diag["n_components"] = int(n)

    sizes = ndimage.sum(air_roi, lbl, range(1, n + 1))
    order = np.argsort(-sizes)

    comps = []
    for idx in order[:20]:
        lab = int(idx) + 1
        m = lbl == lab
        zz, yy, xx = np.where(m)
        comps.append({
            "label": lab, "size": int(sizes[idx]),
            "z": (int(zz.min()), int(zz.max())),
            "y": (int(yy.min()), int(yy.max())),
            "x": (int(xx.min()), int(xx.max())),
        })
    diag["top_components"] = comps

    if verbose:
        print("=== v2 分割诊断 ===")
        print(f"空气总量: {diag['air_total']:,}")
        print(f"ROI 内空气: {diag['air_in_roi']:,}")
        print(f"ROI = z[{P['nasal_z_min']}:{P['nasal_z_max']}] "
              f"y[{P['nostril_y_cut']}:] x[{P['nasal_x_min']}:{P['nasal_x_max']}]")
        print(f"连通域数: {n}")
        print(f"\n{'#':>3} {'label':>6} {'体素':>10} {'z范围':>12} {'y范围':>12} {'x范围':>12}")
        for i, c in enumerate(comps[:12]):
            print(f"{i:>3} {c['label']:>6} {c['size']:>10,} "
                  f"{str(c['z']):>12} {str(c['y']):>12} {str(c['x']):>12}")

    # ---------- 4. 选取主气道 ----------
    if not comps:
        return {"ok": False, "diagnostics": diag}

    # 主气道 = 最大连通域
    main_label = comps[0]["label"]
    main_mask = lbl == main_label
    diag["main_label"] = main_label
    diag["main_size"] = int(main_mask.sum())

    # ---------- 5. 形态学清理 ----------
    cleaned = ndimage.binary_closing(main_mask, structure=np.ones((3, 3, 3)))
    # 保留最大的
    lbl2, n2 = ndimage.label(cleaned, structure=np.ones((3, 3, 3)))
    if n2 > 1:
        s2 = ndimage.sum(cleaned, lbl2, range(1, n2 + 1))
        cleaned = lbl2 == (int(np.argmax(s2)) + 1)

    diag["final_size"] = int(cleaned.sum())

    if verbose:
        print(f"\n主连通域 label={main_label} 体素={diag['main_size']:,}")
        print(f"形态学清理后: {diag['final_size']:,}")

    return {
        "ok": True,
        "mask": cleaned,
        "roi": roi,
        "air": air,
        "diagnostics": diag,
        "params": P,
    }


def render_mask_check(vol, mask, outdir, z_list=None, prefix="seg"):
    """渲染分割结果叠加图"""
    from PIL import Image
    from nasal_io import window_ct
    nz, ny, nx = vol.shape
    if z_list is None:
        z_list = [140, 160, 180, 200, 220, 240, 260]

    tiles = []
    for z in z_list:
        u8 = window_ct(vol[z], 800, 2000)
        rgb = np.stack([u8, u8, u8], axis=-1).copy()
        m = mask[z]
        rgb[m, 0] = 255
        rgb[m, 1] = 60
        rgb[m, 2] = 60
        fn = os.path.join(outdir, f"{prefix}_z{z:04d}.png")
        Image.fromarray(rgb).save(fn)
        tiles.append((z, fn, int(m.sum())))

    # 拼图
    if tiles:
        imgs = [np.array(Image.open(fn)) for _, fn, _ in tiles]
        cols = min(4, len(imgs))
        rows = (len(imgs) + cols - 1) // cols
        h, w = imgs[0].shape[:2]
        sc = 0.5
        h2, w2 = int(h * sc), int(w * sc)
        canvas = np.zeros((rows * h2, cols * w2, 3), dtype=np.uint8)
        for i, im in enumerate(imgs):
            r, c = divmod(i, cols)
            canvas[r*h2:(r+1)*h2, c*w2:(c+1)*w2] = np.array(Image.fromarray(im).resize((w2, h2)))
        grid = os.path.join(outdir, f"{prefix}_grid.png")
        Image.fromarray(canvas).save(grid)
        return grid, tiles
    return None, []


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from nasal_io import load_dicom_series

    vol, sp, org, meta = load_dicom_series(
        r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
    print(f"体积 {vol.shape} 间距 {sp}\n")

    res = segment_nasal_airway_v2(vol, sp)

    if res["ok"]:
        outdir = r"D:\项目\鼻腔建模\work\02_segment"
        os.makedirs(outdir, exist_ok=True)
        grid, tiles = render_mask_check(vol, res["mask"], outdir)
        print(f"\n=== 渲染检查图 ===")
        for z, fn, n in tiles:
            print(f"  z={z}: 掩膜 {n:,} 体素 -> {os.path.basename(fn)}")
        if grid:
            print(f"  拼图 -> {grid}")

        # 保存掩膜
        np.save(os.path.join(outdir, "nasal_mask_v2.npy"), res["mask"])
        import json
        with open(os.path.join(outdir, "seg_diagnostics.json"), "w", encoding="utf-8") as f:
            json.dump(res["diagnostics"], f, ensure_ascii=False, indent=2)
        print(f"  掩膜已保存")
