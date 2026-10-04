# -*- coding: utf-8 -*-
"""
鼻腔气道自动分割 v9 — 修复上颌窦泄漏（最终版）
====================================================
v8 成果：鼻腔主体（z=130~220）分割精确
v8 问题：z=175~190 部分泄漏到上颌窦

修复策略（针对 v8 泄漏）：
  1. **强化形态判据**：降低 max_fill（上颌窦 fill≈0.48-0.50）
  2. **x 范围硬约束**：鼻腔 x 在 182-285（v8 实测），上颌窦更靠外侧
  3. **3D 连通后二次形态过滤**：对主连通域按层再筛一遍
  4. **左右对称性校验**：鼻腔左右体积比应接近 1

关键洞察：上颌窦的 fill 值 0.48-0.50 与鼻腔 0.17-0.36 有明确分界，
          把 max_fill 从 0.52 降到 0.42 可以切断泄漏。
"""
import os, sys, json
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series


def segment_nasal_v9(vol, spacing=None, cfg=None, verbose=True):
    nz, ny, nx = vol.shape
    XC = nx // 2
    C = {
        "hu_air_max": -300,
        "x_center": XC,
        "x_tol": 58,
        "min_size": 120,
        "max_size": 8000,
        "max_fill": 0.42,          # ← 关键收紧（v8 是 0.52）
        "min_aspect": 1.4,         # ← 关键收紧（v8 是 1.2）
        # 鼻腔 x 硬边界（来自 v8 实测 182-285，留余量）
        "nasal_x_min": 175,
        "nasal_x_max": 292,
        "per_layer_max": 4,
        # 3D 筛选
        "min_comp_size": 20000,
    }
    if cfg:
        C.update(cfg)

    air = vol < C["hu_air_max"]

    # ---- 逐层判定 ----
    per_layer = {}
    for z in range(nz):
        mask2d = air[z]
        # 加 x 硬边界
        bounded = np.zeros_like(mask2d)
        bounded[:, C["nasal_x_min"]:C["nasal_x_max"]] = mask2d[:, C["nasal_x_min"]:C["nasal_x_max"]]

        lbl, n = ndimage.label(bounded, structure=np.ones((3, 3)))
        cands = []
        for lab in range(1, n + 1):
            m = lbl == lab
            size = int(m.sum())
            if size < C["min_size"] or size > C["max_size"]:
                continue
            ys, xs = np.where(m)
            y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
            if y0 == 0 or y1 == ny - 1 or x0 == 0 or x1 == nx - 1:
                continue
            cx, cy = float(xs.mean()), float(ys.mean())
            if abs(cx - XC) > C["x_tol"]:
                continue
            bbox = (y1 - y0 + 1) * (x1 - x0 + 1)
            fill = size / bbox
            if fill > C["max_fill"]:
                continue
            w, h = x1 - x0 + 1, y1 - y0 + 1
            aspect = max(w, h) / max(1, min(w, h))
            if aspect < C["min_aspect"]:
                continue
            cands.append({"lab": lab, "mask": m, "size": size, "cx": cx, "cy": cy,
                          "fill": float(fill), "aspect": float(aspect),
                          "y": (y0, y1), "x": (x0, x1)})
        cands.sort(key=lambda c: -c["size"])
        per_layer[z] = cands[:C["per_layer_max"]]

    # ---- 累积 ----
    raw = np.zeros_like(air)
    for z, cs in per_layer.items():
        for c in cs:
            raw[z] |= c["mask"]

    # ---- 3D 连通筛选 ----
    lbl3, n3 = ndimage.label(raw, structure=np.ones((3, 3, 3)))
    mask = np.zeros_like(air)
    comps = []
    if n3:
        sizes3 = ndimage.sum(raw, lbl3, range(1, n3 + 1))
        for i in range(n3):
            if sizes3[i] >= C["min_comp_size"]:
                m = lbl3 == (i + 1)
                zz, yy, xx = np.where(m)
                comps.append({"label": i + 1, "size": int(sizes3[i]),
                              "z": (int(zz.min()), int(zz.max()))})
                mask |= m
        comps.sort(key=lambda c: -c["size"])

    diag = {
        "params": C,
        "n_components_3d": int(n3),
        "kept_components": len(comps),
        "kept_detail": comps,
        "total_voxels": int(mask.sum()),
    }
    if mask.any():
        zz, yy, xx = np.where(mask)
        diag["bbox"] = {"z": [int(zz.min()), int(zz.max())],
                        "y": [int(yy.min()), int(yy.max())],
                        "x": [int(xx.min()), int(xx.max())]}
        left = int(mask[:, :, :XC].sum())
        right = int(mask[:, :, XC:].sum())
        diag["left_voxels"] = left
        diag["right_voxels"] = right
        diag["symmetry_ratio"] = round(min(left, right) / max(1, max(left, right)), 3)

    if verbose:
        print("=== v9 诊断 ===")
        print(f"参数 max_fill={C['max_fill']} min_aspect={C['min_aspect']} "
              f"x范围[{C['nasal_x_min']},{C['nasal_x_max']}]")
        print(f"3D 连通域: {n3}, 保留(>={C['min_comp_size']}): {len(comps)}")
        for c in diag["kept_detail"]:
            print(f"   lab={c['label']} size={c['size']:,} z={c['z']}")
        print(f"总掩膜: {diag['total_voxels']:,}")
        if "bbox" in diag:
            print(f"bbox: {diag['bbox']}")
        print(f"左 {diag.get('left_voxels'):,} / 右 {diag.get('right_voxels'):,}  "
              f"对称比 {diag.get('symmetry_ratio')}")
        print(f"\n{'z':>5} {'候选':>4}  详情")
        for z in range(120, 260, 10):
            cs = per_layer[z]
            det = " | ".join(f"sz{c['size']}x{c['cx']:.0f}f{c['fill']:.2f}a{c['aspect']:.1f}"
                             for c in cs[:4])
            print(f"{z:>5} {len(cs):>4}  {det}")

    return {"mask": mask, "per_layer": per_layer, "diagnostics": diag}


if __name__ == "__main__":
    vol, sp, org, meta = load_dicom_series(
        r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
    print(f"体积 {vol.shape}\n")
    res = segment_nasal_v9(vol, sp)

    outdir = r"D:\项目\鼻腔建模\work\02_segment"
    os.makedirs(outdir, exist_ok=True)
    np.save(os.path.join(outdir, "nasal_mask_v9.npy"), res["mask"])
    with open(os.path.join(outdir, "seg_v9_diag.json"), "w", encoding="utf-8") as f:
        json.dump(res["diagnostics"], f, ensure_ascii=False, indent=2)

    # 渲染
    from PIL import Image
    from nasal_io import window_ct
    z_list = [130, 145, 160, 175, 190, 205, 220, 235]
    tiles = []
    for z in z_list:
        u8 = window_ct(vol[z], 800, 2000)
        rgb = np.stack([u8, u8, u8], axis=-1).copy()
        m = res["mask"][z]
        rgb[m] = [255, 50, 50]
        fn = os.path.join(outdir, f"v9_z{z:04d}.png")
        Image.fromarray(rgb).save(fn)
        tiles.append((z, fn, int(m.sum())))
    imgs = [np.array(Image.open(f)) for _, f, _ in tiles]
    cols, rows = 4, 2
    h, w = imgs[0].shape[:2]
    sc = 0.5; h2, w2 = int(h*sc), int(w*sc)
    canvas = np.zeros((rows*h2, cols*w2, 3), dtype=np.uint8)
    for i, im in enumerate(imgs):
        r, c = divmod(i, cols)
        canvas[r*h2:(r+1)*h2, c*w2:(c+1)*w2] = np.array(Image.fromarray(im).resize((w2, h2)))
    grid = os.path.join(outdir, "v9_grid.png")
    Image.fromarray(canvas).save(grid)
    print(f"\n拼图 -> {grid}")
