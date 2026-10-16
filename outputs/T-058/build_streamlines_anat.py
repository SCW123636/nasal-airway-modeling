# -*- coding: utf-8 -*-
"""
T-058 · b15 解剖斜切扩展域（口咽截断出口）流线重追踪
—— 替换 T-057 的轴位切产物（源场口径已过期）

输入：outputs/T-058/vtk_anat/t600/（源：WSL t058_chain_anat/b15/foam_maxh1，只读复制）
口径：与 T-057/T-049 同引擎（vtkStreamTracer）、同种子（seed=7，每侧 60 种子）→ 与轴位切可比；
      唯一差异 = 出口切面口径（轴位切 → 解剖斜切⊥局部气道轴，用户 2026-10-16 裁定）。
Δp 锚点：17.119542 Pa（T-058 metrics，postProcessing 提取 ×ρ1.2）
轴位切对照：18.267178 Pa（T-054）—— 并列标注为「切面口径差异」（−6.28%），不是修正。
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "work" / "lib"))
from flow_streamlines import (classify_endpoints, extract_field,  # noqa: E402
                              render_html, trace_lines_vtk)

HERE = Path(__file__).resolve().parent
VTK = HERE / "vtk_anat" / "t600"
OUTLET = "oropharynx_truncation_outlet"

DP_EXT = 17.119542030795298         # T-058 解剖斜切（metrics_t058_b15_oroext.json）
DP_AXIAL = 18.26717809927325        # T-054 轴位切（历史对照）

print("== 提取 + 追踪（解剖斜切扩展域）", flush=True)
field = extract_field(VTK, outlet=OUTLET)
lines = trace_lines_vtk(VTK, n_seed=60, seed=7)
core = classify_endpoints(field, lines, outlet=OUTLET)

lens = [l["length_mm"] for l in lines]
result = {
    "task": "T-058 b15 anatomical-oblique extended domain streamlines",
    "domain": "extended（鼻+鼻咽+可见口咽，出口 = oropharynx_truncation_outlet ▸ 解剖斜切⊥局部气道轴）",
    "engine": "vtkStreamTracer (ParaView kernel, RK45 + library interpolation)",
    "seed": 7, "n_seed_per_side": 60,
    "n_lines": core["n_lines"], "reasons": core["reasons"],
    "speed_mps": core["speed_mps"], "n_points_total": core["n_points_total"],
    "length_mm": {"median": float(np.median(lens)), "max": float(max(lens)),
                  "p10": float(np.percentile(lens, 10))},
    "delta_p_Pa": DP_EXT,
    "delta_p_axial_Pa": DP_AXIAL,
    "clinical_status": "generalisation_test_only_no_human_review",
}
print(json.dumps({k: v for k, v in result.items() if k != "task"}, ensure_ascii=False), flush=True)

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
ax.set_title("b15 解剖斜切扩展域 t600 · Δp %.3f Pa\n共 %d 条 · 抵达口咽出口 %d · 出域 %d · 滞留 %d"
             % (DP_EXT, core["n_lines"], r.get("reached_outlet", 0),
                r.get("exited_wall_region", 0), r.get("stall_near_wall", 0)), fontsize=10)
ax.set_xlabel("x mm", fontsize=8); ax.set_ylabel("y mm", fontsize=8)
ax.set_zlabel("z mm", fontsize=8); ax.tick_params(labelsize=7)
fig.suptitle("b15 口咽扩展域 · 解剖斜切（T-058，653,789 cells）· 同种子 60/侧 · vtkStreamTracer\n"
             "绿=抵达口咽截断出口 红=未抵达", fontsize=11)
fig.tight_layout()
fig.savefig(HERE / "t058_view_anat.png", bbox_inches="tight")
print("写出 t058_view_anat.png", flush=True)

# ---- 交互 HTML
n_reach = core["reasons"].get("reached_outlet", 0)
context = {
    "title": "三维流线 · 腔内速度与静压（b15 扩展域 · 解剖斜切，time=600）",
    "crumb": "鼻腔 CFD 工作台 · 患者流场 <b>b15 · 口咽扩展域 · 解剖斜切（T-058）</b>",
    "sub": "WSL t058_chain_anat/b15（b15 maxh1，S-A 预设）· time index 600 · 653,789 单元（checkMesh）",
    "badges": [("", "工程屏通过（T-058 M2 四判据）"), ("", "未临床复核")],
    "honesty_summary": "工程屏通过但非临床结果 · 后处理级流线 · 未经人体复核 · 坐标未归位",
    "honesty": [
        "该场 Time=600 正常 End，T-058 记录 M2 四判据全过（Δp <b>17.120 Pa</b> 入带 / 不平衡 6.0e-8 / "
        "monitor 1.11e-4 / 不崩）；但仍是<b>层流、未过 N6 解剖门</b>的工程试算场，"
        "此图<b>不能用于临床结论</b>；",
        "出口切面口径 = <b>解剖斜切</b>（⊥局部气道轴；用户 2026-10-16 裁定「按照人体构造来就好，斜切」）；"
        "出口帽 <b>126.89 mm²</b>（mesh 阶段）/ 125.85 mm²（开口阶段）。轴位切（T-054：112.51 mm² mesh / "
        "111.00 opening）为<b>历史口径</b>，二者 Δp 17.120 vs 18.267 Pa（<b>−6.28%</b>）属切面口径差，"
        "<b>不是修正</b>；",
        "出口为口咽底<b>工程截断面</b>（<code>oropharynx_truncation_outlet</code>），<b>缺下咽-喉下游阻力</b> → "
        "Δp 偏低估方向已知；",
        "流线由 vtkStreamTracer（ParaView 内核）追踪，属<b>后处理级</b>；"
        "定量一律以 postProcessing 的 <code>surfaceFieldValue</code> 为准；",
        "未见人体复核：<code>clinical_status: generalisation_test_only_no_human_review</code>；",
        "坐标尺为<b>求解器坐标</b>（mm），未做 LPS/解剖方位归位，x/y/z 不等于「左右/前后/上下」。",
    ],
    "stats": [
        ("Δp（解剖斜切）", "%.3f Pa" % DP_EXT, "T-058 postProcessing 锚点"),
        ("Δp（轴位切对照）", "%.3f Pa" % DP_AXIAL, "T-054 历史口径 · 差 −6.28% 非修正"),
        ("抵达口咽出口", "%d / %d 条" % (n_reach, core["n_lines"]),
         "占 %d%%" % round(100 * n_reach / max(core["n_lines"], 1))),
        ("沿流线速度中位", "%.2f m/s" % core["speed_mps"]["median"],
         "max %.2f" % core["speed_mps"]["max"]),
    ],
    "facts": [
        ("来源", "WSL <code>t058_chain_anat/b15/foam_maxh1</code> · time index <code>600</code>"),
        ("域", "<b>扩展域</b>（鼻+鼻咽+可见口咽）· 出口 <code>oropharynx_truncation_outlet</code> 126.89 mm²（mesh）"),
        ("网格", "653,789 单元（checkMesh）· 非正交 76.56° · det&lt;0.001 482"),
        ("工况", "双鼻孔各 1.25e-4 m³/s（15 L/min，固定 50:50）· 出口 p=0 gauge"),
        ("口径", "T-006/T-041/T-042/T-054/T-058 口径，<b>不可与 T-021/T-029 混用</b>"),
        ("追踪口径", "同 T-057/T-049（vtkStreamTracer，seed=7，每侧 60 种子）→ 与轴位切可比"),
        ("临床状态", "<code>generalisation_test_only_no_human_review</code>"),
    ],
    "footnote": "vtkStreamTracer（ParaView 内核）追踪；种子两侧鼻孔面各 60 个（同 T-044/T-049/T-057 种子序列）。"
                "本条替换 T-057 的轴位切产物（源场口径过期）。定量 meta 见 t058_streamlines_anat_meta.json（T-058）。",
}
meta = {**core, **{k: v for k, v in result.items()
                   if k in ("task", "domain", "delta_p_Pa", "clinical_status", "seed", "n_seed_per_side")}}
html = render_html(field, lines, meta, context, outlet=OUTLET)
(HERE / "streamlines_b15_anat_t600.html").write_text(html, encoding="utf-8")
(HERE / "t058_streamlines_anat_meta.json").write_text(
    json.dumps({**result, "lines": [{k: v for k, v in l.items() if k not in ("pts_mm", "spd", "pPa")}
                                    for l in lines]}, ensure_ascii=False, indent=2), "utf-8")
print("写出 streamlines_b15_anat_t600.html / t058_streamlines_anat_meta.json", flush=True)
