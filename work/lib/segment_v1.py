# -*- coding: utf-8 -*-
"""
鼻腔气道自动分割 — 核心算法
=========================================
策略（基于本病例实测解剖）：
  1. 阈值提取空气（HU < -300）
  2. 切断鼻孔处与外部空气的连通（关键步骤，SOP 强调）
  3. 3D 连通域分析，保留与"种子点"连通的鼻腔主气道
  4. 排除鼻窦（上颌窦/筛窦/额窦/蝶窦）、乳突气房
  5. 保留鼻孔入口 + 鼻咽出口

本模块为可迭代的实验版本，每一步都输出诊断信息。
"""
import os
import numpy as np
from scipy import ndimage


# ============ 可调参数（全部显式，无隐藏默认） ============
PARAMS = {
    "hu_air_max": -300,        # 空气阈值上界 HU
    "hu_bone_min": 300,        # 骨阈值下界 HU
    "nose_cut_y_max": None,    # 鼻孔切断平面（y 坐标），None=自动
    "seed_z": None,            # 种子点 z（自动=鼻腔最宽层）
    "seed_y": None,
    "seed_x": None,
    "min_component": 500,      # 最小连通域体素（去噪）
}


def make_air_mask(vol, hu_max=-300):
    """步骤1：阈值提取空气"""
    return vol < hu_max


def find_nose_tip(vol, spacing, hu_air=-300):
    """
    步骤2a：自动定位鼻尖/鼻孔平面
    原理：鼻尖是面部最前突出点。在存在鼻腔的层区间内，
          找 y 坐标最小的软组织/骨边界。
    返回 (y_nose_tip_index, 诊断信息)
    """
    nz, ny, nx = vol.shape
    air = vol < hu_air
    body = ~air   # 非空气 = 组织+骨

    # 鼻尖：面部轮廓最前点。逐层找 body 的 y 最小值
    y_front = np.full(nz, ny, dtype=int)
    for z in range(nz):
        ys = np.where(body[z].any(axis=1))[0]
        if len(ys):
            y_front[z] = ys.min()

    # 鼻尖所在层 = y_front 最小的层（最向前突出）
    valid = y_front < ny
    if valid.sum() == 0:
        return None, {"error": "no body found"}
    z_nose = int(np.argmin(np.where(valid, y_front, ny)))
    y_nose = int(y_front[z_nose])

    return y_nose, {
        "z_nose_tip": z_nose,
        "y_nose_tip": y_nose,
        "y_front_min": int(y_front[valid].min()),
        "y_front_profile_sample": [(int(z), int(y_front[z]))
                                    for z in range(0, nz, max(1, nz // 20))
                                    if valid[z]],
    }


def cut_external_air(air, y_cut):
    """
    步骤2b：在鼻孔平面之前（y < y_cut）的像素标记为外部，不参与主气道
    注意：这里只是标记，不删除数据
    """
    external = np.zeros_like(air)
    external[:, :y_cut, :] = True
    return external


def find_nasal_seed(vol, air, spacing, z_search=None):
    """
    步骤3a：自动寻找鼻腔主气道种子点
    原理：鼻腔位于身体正中（x 中心附近），鼻中隔两侧。
          在鼻腔中段层，找"靠近 x 中心 + 被骨包围 + 连通域较大"的空气区。
    """
    nz, ny, nx = vol.shape
    x_center = nx // 2

    if z_search is None:
        z_search = range(nz // 3, 2 * nz // 3)

    best = None
    candidates = []
    for z in z_search:
        lbl, n = ndimage.label(air[z], structure=np.ones((3, 3)))
        if n == 0:
            continue
        for lab in range(1, n + 1):
            ys, xs = np.where(lbl == lab)
            size = len(ys)
            if size < 200:
                continue
            # 靠近 x 中心
            x_mid = xs.mean()
            dist_x = abs(x_mid - x_center)
            # 该区域在 y 上是否"被包围"（左右有组织）
            y_mid = ys.mean()
            candidates.append({
                "z": z, "lab": lab, "size": size,
                "x_mid": float(x_mid), "y_mid": float(y_mid),
                "x_min": int(xs.min()), "x_max": int(xs.max()),
                "y_min": int(ys.min()), "y_max": int(ys.max()),
                "dist_x": float(dist_x),
            })

    # 排序：优先靠近中线 + 体积大
    candidates.sort(key=lambda c: (c["dist_x"] / (c["size"] ** 0.5)))
    return candidates[:20]


def segment_nasal_airway(vol, spacing, params=None, verbose=True):
    """
    主分割流程
    返回 dict: {mask, seed, diagnostics, ...}
    """
    P = dict(PARAMS)
    if params:
        P.update(params)

    nz, ny, nx = vol.shape
    diag = {}

    # --- 1. 空气掩膜 ---
    air = make_air_mask(vol, P["hu_air_max"])
    diag["air_voxels"] = int(air.sum())

    # --- 2. 定位鼻尖 ---
    y_nose, nose_info = find_nose_tip(vol, spacing, P["hu_air_max"])
    diag["nose_tip"] = nose_info

    # --- 3. 候选种子点 ---
    cands = find_nasal_seed(vol, air, spacing)
    diag["seed_candidates"] = cands

    if verbose:
        print("=== 分割诊断 ===")
        print(f"空气体素: {diag['air_voxels']:,}")
        print(f"鼻尖: z={nose_info.get('z_nose_tip')} y={nose_info.get('y_nose_tip')}")
        print(f"\n种子候选（前10，按靠近中线排序）:")
        print(f"{'#':>3} {'z':>5} {'size':>8} {'x_mid':>8} {'y_mid':>8} {'dist_x':>8} "
              f"{'x范围':>14} {'y范围':>14}")
        for i, c in enumerate(cands[:10]):
            print(f"{i:>3} {c['z']:>5} {c['size']:>8,} {c['x_mid']:>8.1f} {c['y_mid']:>8.1f} "
                  f"{c['dist_x']:>8.1f} {c['x_min']:>6}-{c['x_max']:<6} "
                  f"{c['y_min']:>6}-{c['y_max']:<6}")

    return {"air": air, "diagnostics": diag, "y_nose": y_nose}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from nasal_io import load_dicom_series

    vol, sp, org, meta = load_dicom_series(
        r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
    print(f"体积 {vol.shape} 间距 {sp}")

    result = segment_nasal_airway(vol, sp)
