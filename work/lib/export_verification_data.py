# -*- coding: utf-8 -*-
"""导出「检验数据包」：参考空气掩膜(npz) + 证据包(json)，并对 anchors 做独立复现交叉校验。
供更强模型离线验证/优化使用。纯 CT 驱动，不依赖任何预分割文件。
"""
import os, sys, json
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series

ROOT = r"D:\项目\鼻腔建模"
DICOM = os.path.join(ROOT, "work", "00_dicom", "bone")
CAL = os.path.join(ROOT, "work", "03_calib")

vol, sp, org, meta = load_dicom_series(DICOM, verbose=False)
nz, ny, nx = vol.shape
dx, dy, dz = sp
air = vol < -300

# ============ 核心：体内/体外空气分离（与 calib_v2.py 完全一致） ============
outside = np.zeros_like(air)
for z in range(nz):
    a = air[z]
    if not a.any():
        continue
    lbl, n = ndimage.label(a, structure=np.ones((3, 3)))
    edge_labels = set(lbl[0, :]) | set(lbl[-1, :]) | set(lbl[:, 0]) | set(lbl[:, -1])
    edge_labels.discard(0)
    if edge_labels:
        outside[z] = np.isin(lbl, list(edge_labels))
inside = air & (~outside)

n_out = int(outside.sum())
n_in = int(inside.sum())
print(f"体外空气 {n_out:,}  体内空气 {n_in:,}  (体内/总空气={n_in/(n_out+n_in):.3f})")

# ============ 独立复现锚点（复制 calib_v2 的判定逻辑，验证可复现） ============
rows = []
for z in range(nz):
    m = inside[z]
    n = int(m.sum())
    if n == 0:
        rows.append({"z": z, "n": 0, "x_min": -1, "x_max": -1, "x_span": 0,
                     "cx": -1.0, "ncomp": 0})
        continue
    ys, xs = np.where(m)
    lbl, nc = ndimage.label(m, structure=np.ones((3, 3)))
    rows.append({"z": z, "n": n, "x_min": int(xs.min()), "x_max": int(xs.max()),
                 "x_span": int(xs.max() - xs.min() + 1),
                 "cx": round(float(xs.mean()), 2), "ncomp": int(nc)})
prof = np.array([r["n"] for r in rows], dtype=float)
cx = np.array([r["cx"] for r in rows], dtype=float)
span = np.array([r["x_span"] for r in rows], dtype=float)

def smooth(a, k=9):
    if len(a) < k:
        return a
    return np.convolve(a, np.ones(k) / k, mode="same")

ps = smooth(prof, 9)
dps = np.gradient(ps)
nz_any = np.where(prof > 0)[0]
z_lo, z_hi = int(nz_any.min()), int(nz_any.max())
search_from = z_lo + 15
i_rise = search_from + int(np.argmax(dps[search_from:]))
i = i_rise
while i > search_from and dps[i] > 0:
    i -= 1
z_nostril = i
z_peak = int(z_nostril + np.argmax(ps[z_nostril:]))
i_fall = z_peak + int(np.argmin(dps[z_peak:]))
z_widest = int(z_nostril + np.argmax(span[z_nostril:z_peak + 1]))
med = float(np.median(cx[z_nostril:z_peak + 1]))

recomputed = {
    "z_nostril_entry": z_nostril,
    "z_nasal_peak": z_peak,
    "z_nasopharynx": i_fall,
    "z_widest": z_widest,
    "x_center_nasal": int(round(med)),
    "nasal_span_mm": round((i_fall - z_nostril) * dz, 2),
}

# ============ 与已存 landmarks.json 交叉比对 ============
lm = json.load(open(os.path.join(CAL, "landmarks.json"), encoding="utf-8"))
claimed = {k: lm["anchors"][k]["z"] for k in
           ("z_nostril_entry", "z_nasal_peak", "z_nasopharynx", "z_widest")}
claimed["x_center_nasal"] = lm["anchors"]["x_center_nasal"]["x"]
claimed["nasal_span_mm"] = lm["nasal_span_mm"]
diff = {k: recomputed[k] - claimed[k] for k in recomputed}
print("claims vs recompute diff:", diff)
assert all(v == 0 for v in diff.values()), f"锚点不可复现! diff={diff}"

# ============ 关键层 profile 取值（供验证"上升沿/峰值/下降"故事） ============
def in_count(z):
    return int(inside[z].sum())
prof_key = {z: in_count(z) for z in (z_lo, z_nostril, z_nostril + 20,
                                      (z_nostril + z_peak) // 2, z_peak,
                                      z_peak + 20, i_fall, z_hi)}

# ============ 导出参考空气掩膜（压缩） ============
np.savez_compressed(os.path.join(CAL, "inside_air.npz"), inside=inside.astype(np.uint8))
print("inside_air.npz 已导出")

# ============ 证据包 ============
ev = {
    "purpose": "鼻腔空气域标定方法的离线验证数据包。供独立模型复算锚点、校验体内/体外分离、评估 v9 失效证据。",
    "data_provenance": {
        "dicom_dir": DICOM,
        "shape": [nz, ny, nx],
        "spacing_xyz_mm": [round(dx, 6), round(dy, 6), round(dz, 6)],
        "is_isotropic": abs(dx - dy) < 1e-6 and abs(dx - dz) < 1e-3,
        "dz_unique_n": 1,
        "origin_ipp_first": [round(x, 6) for x in org],
        "rescale_intercept": -1024,
        "alignment_note": "bone 与 soft 两套 IPP/IOP/尺寸差值全 0，共享同一体素网格，无需配准",
        "ipp_last": [-96.492188, -261.400024, round(org[2] + (nz - 1) * dz, 6)],
        "z_span_mm": round((nz - 1) * dz, 2),
    },
    "air_threshold_hu": -300,
    "separation": {
        "method": "每层从图像四边对 air 做 flood fill，可达=体外；air & ~体外=体内",
        "outside_voxels": n_out,
        "inside_voxels": n_in,
        "inside_fraction_of_air": round(n_in / (n_out + n_in), 4),
    },
    "anchors_claimed": claimed,
    "anchors_recomputed": recomputed,
    "anchor_reproducibility_diff": diff,
    "anchor_mm_z": {
        k: round(org[2] + lm["anchors"][k]["z"] * dz, 3)
        for k in ("z_nostril_entry", "z_nasal_peak", "z_nasopharynx", "z_widest")
    },
    "profile_at_key_z": prof_key,
    "v9_failure_evidence": {
        "source": "work/01_inspect/v9分割失效诊断报告.md + .workbuddy/probe/mask_hu_check.json",
        "mask_voxels": 355907,
        "mask_hu_frac_below_-300": 1.0,
        "mask_hu_frac_above_0": 0.0,
        "mask_hu_median": -999,
        "mask_bbox_z": [129, 221],
        "bbox_air_total": 862257,
        "bbox_air_captured": 355907,
        "bbox_capture_rate": 0.4128,
        "symmetry_ratio_L_R": 0.175,
        "symmetry_L": 302834,
        "symmetry_R": 53073,
        "rejected_main_domain_example": "z=140 size=77615 cx=250.3 fill=0.296 -> 触边,太大,aspect=1.00",
        "broken_criteria": ["max_size=8000 (实际主体77k-89k,差1数量级)",
                              "触边判据(鼻腔气柱本就连通到扫描边界,与解剖事实冲突)",
                              "aspect=1.00 (包围盒近正方形,无分辨力)"],
    },
    "verified_vs_assumed": {
        "verified": [
            "物理坐标各向同性 0.35mm、两套序列像素级对齐",
            "锚点可由 CT 独立复现(diff=0)",
            "鼻腔跨度 51.1mm 落在成人解剖区间(50-70mm)",
            "v9 掩膜 100% 为空气(HU 纯净),仅选错空气块",
            "体内/体外分离在本例干净(口腔/鼻腔/咽被红层覆盖,体外在轮廓外)",
        ],
        "assumed_or_unverified": [
            "z_nostril_entry=62 可能略早(该层红主要在口腔区,真鼻孔或更靠后),需人工目视确认",
            "体内空气≠鼻腔: 仍含口腔、咽、鼻窦,需 z 切割+鼻窦排除才得纯鼻腔",
            "flood fill 为逐层2D,若头颈贴图像边缘会漏;本例未触发但需联调验证",
            "仅单病例验证,锚点检测算法的跨病例泛化性未知",
            "CFD 边界条件(SOP 15L/min→0Pa vs 录屏 0→18Pa)、稳态vs瞬态未决",
        ],
    },
    "optimization_targets": [
        "T1 用 3D 连通域+鼻孔平面切割替代逐层 触边/最大尺寸筛选(解决59%漏采)",
        "T2 鼻窦排除: 在窦口最窄处按解剖位置截断(上颌窦/筛窦/蝶窦/额窦)",
        "T3 把硬编码魔数(x_tol/max_size/z范围)全部改为锚点相对量(距鼻孔Xmm)",
        "T4 体内/体外分离改为 3D 体连通 flood fill(从扫描孔背景灌入)以提升鲁棒性",
        "T5 多病例回归: 锚点检测在≥3例上求召回/误检,定容差",
        "T6 对称比+捕获率做成每次运行的强制验收闸门(目标对称比≥0.7)",
    ],
    "verification_checklist": [
        "C1 复跑 calib_v2.py, 确认 anchors 与本包 recomputed 完全一致",
        "C2 用 inside_air.npz 独立重算面积剖面, 确认 z_nostril/z_peak/z_nasopharynx 拐点",
        "C3 取第二份 CT 跑同一流程, 报告锚点是否稳定(泛化性核心检验)",
        "C4 目视 z=62 层, 判断鼻孔入口是否偏早",
        "C5 量化 red(体内空气)中'非鼻腔'占比(口腔+咽+鼻窦)",
        "C6 构造头颈贴边合成数据, 验证 flood fill 是否泄漏",
    ],
}
with open(os.path.join(CAL, "verification_evidence.json"), "w", encoding="utf-8") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print("verification_evidence.json 已导出")
print("OK")
