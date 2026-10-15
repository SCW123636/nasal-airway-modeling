# -*- coding: utf-8 -*-
"""
T-057 · b15 扩展域（口咽截断出口）收敛终态流线重追踪
输入：outputs/T-057/vtk/t600/（源：WSL patient_cfd/t054_b15_oroext/foam_maxh1，只读复制）
口径：与 T-049 同引擎（vtkStreamTracer）、同种子（seed=7，每侧 60 种子）→ 两例可比；
      唯一差异 = 域口径（短域 nasopharynx_outlet → 扩展域 oropharynx_truncation_outlet）
Δp 锚点：18.267 Pa（T-054 metrics，postProcessing 提取 ×ρ1.2）
短域对照：10.294 Pa（T-042/T-041 同法提取）——并列标注为「域口径差异」，不是修正。
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "work" / "lib"))
from flow_streamlines import (classify_endpoints, extract_field,  # noqa: E402
                              render_html, trace_lines_vtk)

HERE = Path(__file__).resolve().parent
VTK = HERE / "vtk" / "t600"
OUTLET = "oropharynx_truncation_outlet"

DP_EXT = 18.26717809927325          # T-054 扩展域（metrics_t054_b15_oroext.json）
DP_SHORT = 10.294                   # T-042 短域（历史参考）

print("== 提取 + 追踪（扩展域）", flush=True)
field = extract_field(VTK, outlet=OUTLET)
lines = trace_lines_vtk(VTK, n_seed=60, seed=7)
core = classify_endpoints(field, lines, outlet=OUTLET)

lens = [l["length_mm"] for l in lines]
result = {
    "task": "T-057 b15 oropharynx-extended domain streamlines",
    "domain": "extended（鼻+鼻咽+可见口咽，出口 = oropharynx_truncation_outlet 工程截断）",
    "engine": "vtkStreamTracer (ParaView kernel, RK45 + library interpolation)",
    "seed": 7, "n_seed_per_side": 60,
    "n_lines": core["n_lines"], "reasons": core["reasons"],
    "speed_mps": core["speed_mps"], "n_points_total": core["n_points_total"],
    "length_mm": {"median": float(np.median(lens)), "max": float(max(lens)),
                  "p10": float(np.percentile(lens, 10))},
    "delta_p_Pa": DP_EXT,
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
ax.set_title("b15 扩展域 t600 · Δp %.3f Pa\n共 %d 条 · 抵达口咽出口 %d · 出域 %d · 滞留 %d"
             % (DP_EXT, core["n_lines"], r.get("reached_outlet", 0),
                r.get("exited_wall_region", 0), r.get("stall_near_wall", 0)), fontsize=10)
ax.set_xlabel("x mm", fontsize=8); ax.set_ylabel("y mm", fontsize=8)
ax.set_zlabel("z mm", fontsize=8); ax.tick_params(labelsize=7)
fig.suptitle("b15 口咽扩展域（T-054，636,342 cells）· 同种子 60/侧 · vtkStreamTracer\n"
             "绿=抵达口咽截断出口 红=未抵达", fontsize=11)
fig.tight_layout()
fig.savefig(HERE / "t057_view.png", bbox_inches="tight")
print("写出 t057_view.png", flush=True)

# ---- 交互 HTML
n_reach = core["reasons"].get("reached_outlet", 0)
context = {
    "title": "三维流线 · 腔内速度与静压（b15 扩展域，time=600）",
    "crumb": "鼻腔 CFD 工作台 · 患者流场 <b>b15 · 口咽扩展域（T-054）</b>",
    "sub": "WSL patient_cfd/t054_b15_oroext（b15 maxh1，S-A 预设）· time index 600 · 636,342 单元",
    "badges": [("", "工程屏通过（T-054 M2 四判据）"), ("", "未临床复核")],
    "honesty_summary": "工程屏通过但非临床结果 · 后处理级流线 · 未经人体复核 · 坐标未归位",
    "honesty": [
        "该场 Time=600 正常 End，T-054 记录 M2 四判据全过（Δp <b>18.267 Pa</b> 入带 / 不平衡 3.49e-8 / "
        "monitor 1.24e-4 / 不崩）；但仍是<b>层流、未过 N6 解剖门</b>的工程试算场，"
        "此图<b>不能用于临床结论</b>；",
        "域口径 = <b>扩展域</b>（鼻+鼻咽+可见口咽），出口为口咽底<b>工程截断面</b>"
        "（<code>oropharynx_truncation_outlet</code>，112.51 mm²），<b>缺下咽-喉下游阻力</b> → "
        "Δp 偏低估方向已知；短域（T-042，10.294 Pa）已降级历史参考，两者<b>只可比作域口径差异</b>，"
        "不是修正；",
        "流线由 vtkStreamTracer（ParaView 内核）追踪，属<b>后处理级</b>；"
        "定量一律以 postProcessing 的 <code>surfaceFieldValue</code> 为准；",
        "未见人体复核：<code>clinical_status: generalisation_test_only_no_human_review</code>；",
        "坐标尺为<b>求解器坐标</b>（mm），未做 LPS/解剖方位归位，x/y/z 不等于「左右/前后/上下」。",
    ],
    "stats": [
        ("Δp（扩展域）", "%.3f Pa" % DP_EXT, "T-054 postProcessing 锚点"),
        ("Δp（短域对照）", "%.3f Pa" % DP_SHORT, "T-042 历史参考 · 口径差异非修正"),
        ("抵达口咽出口", "%d / %d 条" % (n_reach, core["n_lines"]),
         "占 %d%%" % round(100 * n_reach / max(core["n_lines"], 1))),
        ("沿流线速度中位", "%.2f m/s" % core["speed_mps"]["median"],
         "max %.2f" % core["speed_mps"]["max"]),
    ],
    "facts": [
        ("来源", "WSL <code>patient_cfd/t054_b15_oroext/foam_maxh1</code> · time index <code>600</code>"),
        ("域", "<b>扩展域</b>（鼻+鼻咽+可见口咽）· 出口 <code>oropharynx_truncation_outlet</code> 112.51 mm²"),
        ("网格", "636,342 单元（修复后）· 非正交 76.8° · det&lt;0.001 466"),
        ("工况", "双鼻孔各 1.25e-4 m³/s（15 L/min，固定 50:50）· 出口 p=0 gauge"),
        ("口径", "T-006/T-041/T-042/T-054 口径，<b>不可与 T-021/T-029 混用</b>"),
        ("追踪口径", "同 T-049（vtkStreamTracer，seed=7，每侧 60 种子）→ 与短域 t600 可比"),
        ("临床状态", "<code>generalisation_test_only_no_human_review</code>"),
    ],
    "footnote": "vtkStreamTracer（ParaView 内核）追踪；种子两侧鼻孔面各 60 个（同 T-044/T-049 种子序列）。"
                "定量 meta 见 t057_streamlines_meta.json（T-057）。",
}
meta = {**core, **{k: v for k, v in result.items()
                   if k in ("task", "domain", "delta_p_Pa", "clinical_status", "seed", "n_seed_per_side")}}
html = render_html(field, lines, meta, context, outlet=OUTLET)
(HERE / "streamlines_b15_oroext_t600.html").write_text(html, encoding="utf-8")
(HERE / "t057_streamlines_meta.json").write_text(
    json.dumps({**result, "lines": [{k: v for k, v in l.items() if k not in ("pts_mm", "spd", "pPa")}
                                    for l in lines]}, ensure_ascii=False, indent=2), "utf-8")
print("写出 streamlines_b15_oroext_t600.html / meta", flush=True)
