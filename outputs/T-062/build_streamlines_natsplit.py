# -*- coding: utf-8 -*-
"""
T-062 · b15 自然分流路线第一轮（λ=0.52）流线追踪 —— 用户 18:30 期限交付。
源场 = WSL t062_split/b15/eval_001（内层生产链流量驱动 600 步收敛解，
L/R = 1.30e-4 / 1.20e-4 m³/s，总流量 250 mL/s）。
口径：**近似自然分流**（λ=0.52 单点；严格平衡 λ* 需外层割线继续，g=1.426 Pa @0.52）。
引擎/种子与 T-057/T-058 完全一致（vtkStreamTracer，seed=7，每侧 60）→ 可比。
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "work" / "lib"))
from flow_streamlines import (classify_endpoints, extract_field,  # noqa: E402
                              render_html, trace_lines_vtk)

HERE = Path(__file__).resolve().parent
VTK = HERE / "vtk_natsplit" / "t600"
OUTLET = "oropharynx_truncation_outlet"

# T-062 eval_001 监测锚点（Time=600，postProcessing surfaceFieldValue ×ρ1.2）
P_L = 14.87895969190 * 1.2
P_R = 13.69040981572 * 1.2
DP_COMMON = 0.5 * (P_L + P_R)
G_PA = P_L - P_R
DP_5050 = 17.120           # T-058 解剖斜切 50:50 口径（工作台现行）

print("== 提取 + 追踪（b15 自然分流 λ=0.52 第一轮）", flush=True)
field = extract_field(VTK, outlet=OUTLET)
lines = trace_lines_vtk(VTK, n_seed=60, seed=7)
core = classify_endpoints(field, lines, outlet=OUTLET)

lens = [l["length_mm"] for l in lines]
result = {
    "task": "T-062 b15 natural-split (lambda=0.52 first pass) extended domain streamlines",
    "domain": "extended（鼻+鼻咽+可见口咽，出口 = oropharynx_truncation_outlet ▸ 解剖斜切⊥局部气道轴）",
    "engine": "vtkStreamTracer (ParaView kernel, RK45 + library interpolation)",
    "seed": 7, "n_seed_per_side": 60,
    "n_lines": core["n_lines"], "reasons": core["reasons"],
    "speed_mps": core["speed_mps"], "n_points_total": core["n_points_total"],
    "length_mm": {"median": float(np.median(lens)), "max": float(max(lens)),
                  "p10": float(np.percentile(lens, 10))},
    "delta_p_common_Pa": DP_COMMON,
    "p_left_Pa": P_L, "p_right_Pa": P_R, "g_pa": G_PA,
    "lambda_left": 0.52, "left_fraction": 0.52,
    "split_note": "近似自然分流：λ=0.52 单点，p_L−p_R=1.426 Pa 未达 0.05 Pa 平衡容差；严格 λ* 由外层割线继续（eval_002+）",
    "delta_p_5050_Pa": DP_5050,
    "clinical_status": "generalisation_test_only_no_human_review",
}
print(json.dumps({k: v for k, v in result.items() if k != "task"}, ensure_ascii=False), flush=True)

n_reach = core["reasons"].get("reached_outlet", 0)
CONTEXT = {
    "title": "三维流线 · 腔内速度与静压（b15 扩展域 · 自然分流 λ=0.52，time=600）",
    "crumb": "鼻腔 CFD 工作台 · 患者流场 <b>b15 · 口咽扩展域 · 自然分流第一轮（T-062）</b>",
    "sub": "WSL t062_split/b15/eval_001（流量驱动内层，L/R=1.30e-4/1.20e-4 m³/s）· time 600 · 653,789 单元（checkMesh）",
    "badges": [("", "自然分流路线第一轮（近似）"), ("", "外层平衡收敛中"), ("", "未临床复核")],
    "honesty_summary": "近似自然分流（λ=0.52 单点，未达平衡容差）· 工程屏口径 · 后处理级流线 · 未经人体复核",
    "honesty": [
        "本页 = <b>自然分流路线第一轮</b>（λ=0.52，左 52% / 右 48%），内层为 T-058 已验证的"
        "流量驱动 600 步收敛解；<b>不是</b>严格平衡解——p_L−p_R=<b>1.426 Pa</b> 尚未达 0.05 Pa 容差，"
        "严格 λ* 由外层割线继续（eval_002+）；",
        "p_common = <b>%.3f Pa</b>（p_L %.3f / p_R %.3f）；与 T-058 50:50 口径 Δp 17.120 Pa 相差 "
        "<b>+0.13%%</b>——两种口径不属同一序列，正式对照以收敛后的 C5 表为准；" % (DP_COMMON, P_L, P_R),
        "出口为口咽底<b>工程截断面</b>（<code>oropharynx_truncation_outlet</code>），"
        "缺下咽-喉下游阻力 → Δp 偏低估方向已知；",
        "流线由 vtkStreamTracer（ParaView 内核）追踪，属<b>后处理级</b>；"
        "定量一律以 postProcessing 的 <code>surfaceFieldValue</code> 为准；",
        "未见人体复核：<code>clinical_status: generalisation_test_only_no_human_review</code>；",
        "坐标尺为<b>求解器坐标</b>（mm），未做 LPS/解剖方位归位。",
    ],
    "stats": [
        ("p_common（近似自然分流）", "%.3f Pa" % DP_COMMON, "p_L %.3f / p_R %.3f（×ρ1.2）" % (P_L, P_R)),
        ("分流比", "52 : 48", "λ=0.52 首轮；严格 λ* 收敛中"),
        ("对照：50:50 口径 Δp", "%.3f Pa" % DP_5050, "T-058 · 禁与本口径混作同一序列"),
        ("抵达口咽出口", "%d / %d 条" % (n_reach, core["n_lines"]),
         "占 %d%%" % round(100 * n_reach / max(core["n_lines"], 1))),
        ("沿流线速度中位", "%.2f m/s" % core["speed_mps"]["median"],
         "max %.2f" % core["speed_mps"]["max"]),
    ],
    "facts": [
        ("来源", "WSL <code>t062_split/b15/eval_001</code> · time <code>600</code>（T-062 自然分流路线）"),
        ("域", "<b>扩展域</b>（鼻+鼻咽+可见口咽）· 出口 <code>oropharynx_truncation_outlet</code> 解剖斜切"),
        ("工况", "总流量 250 mL/s · 分流比 λ=0.52（L 1.30e-4 / R 1.20e-4 m³/s）· 出口 p=0 gauge"),
        ("口径", "T-062 自然分流路线第一轮 · <b>不可与 T-054/T-058 的 50:50 混作同一序列</b>"),
        ("追踪口径", "同 T-057/T-058（vtkStreamTracer，seed=7，每侧 60 种子）→ 与 50:50 版可比"),
        ("临床状态", "<code>generalisation_test_only_no_human_review</code>"),
    ],
    "footnote": "vtkStreamTracer（ParaView 内核）追踪；种子两侧鼻孔面各 60 个（同 T-044/T-049/T-057/T-058 种子序列）。"
                "本页为 T-062 期限交付的中间产物，严格 λ* 收敛后另行换基。",
}

meta = {**core, **{k: v for k, v in result.items()
                   if k in ("task", "domain", "delta_p_common_Pa", "clinical_status",
                            "seed", "n_seed_per_side", "lambda_left")}}
html = render_html(field, lines, meta, CONTEXT, outlet=OUTLET)
(HERE / "streamlines_b15_natsplit_lam052_t600.html").write_text(html, encoding="utf-8")
(HERE / "t062_streamlines_natsplit_meta.json").write_text(
    json.dumps({**result, "lines": [{k: v for k, v in l.items() if k not in ("pts_mm", "spd", "pPa")}
                                    for l in lines]}, ensure_ascii=False, indent=2), "utf-8")
print("写出 streamlines_b15_natsplit_lam052_t600.html / t062_streamlines_natsplit_meta.json", flush=True)

# ---- 静态对照视图（matplotlib 仅用于呈现，不作定量证据）
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DengXian", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

fig = plt.figure(figsize=(7.6, 6.2), dpi=150)
ax = fig.add_subplot(1, 1, 1, projection="3d")
for l in lines:
    p = l["pts_mm"]
    ax.plot(p[:, 0], p[:, 1], p[:, 2], lw=0.6,
            color="#2a9d4a" if l["reason"] == "reached_outlet" else "#b64e43", alpha=0.75)
ax.view_init(azim=-60, elev=30)
r = core["reasons"]
ax.set_title("b15 自然分流 λ=0.52 扩展域 t600 · p_common %.3f Pa\n共 %d 条 · 抵达口咽出口 %d · 出域 %d · 滞留 %d"
             % (DP_COMMON, core["n_lines"], r.get("reached_outlet", 0),
                r.get("exited_wall_region", 0), r.get("stall_near_wall", 0)), fontsize=10)
fig.savefig(HERE / "t062_view_natsplit_lam052.png", bbox_inches="tight")
print("写出 t062_view_natsplit_lam052.png", flush=True)
