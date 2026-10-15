# -*- coding: utf-8 -*-
"""
T-049 · 收敛终态流线重追踪 + 400/600 定量对照（vtkStreamTracer 引擎，同种子）
输入：outputs/T-049/vtk/{t400,t600}/（源：WSL t042_b15_wssfix，只读复制）
Δp 锚点（postProcessing 字面提取，×1.2）：@400 10.2941 Pa / @600 10.2940 Pa
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "work" / "lib"))
from flow_streamlines import (classify_endpoints, extract_field,  # noqa: E402
                              render_html, trace_lines_vtk)

HERE = Path(__file__).resolve().parent

DP = {"t400": {"p_kin_L": 7.375898106539, "p_kin_R": 9.780951877597,
               "flow_out": 2.499997201439e-04},
      "t600": {"p_kin_L": 7.375558044262, "p_kin_R": 9.781046370923,
               "flow_out": 2.499998681986e-04}}
for k, v in DP.items():
    v["delta_p_Pa"] = 1.2 * (v["p_kin_L"] + v["p_kin_R"]) / 2

result = {"delta_p": DP}
fields, traced = {}, {}
for tag in ("t400", "t600"):
    print("== 提取+追踪", tag, flush=True)
    f = extract_field(HERE / "vtk" / tag)
    lines = trace_lines_vtk(HERE / "vtk" / tag)
    core = classify_endpoints(f, lines)
    fields[tag], traced[tag] = f, lines
    lens = [l["length_mm"] for l in lines]
    result[tag] = {"n_lines": core["n_lines"], "reasons": core["reasons"],
                   "speed": core["speed_mps"], "n_points": core["n_points_total"],
                   "length_mm": {"median": float(np.median(lens)),
                                 "max": float(max(lens)),
                                 "p10": float(np.percentile(lens, 10))}}
    print(json.dumps(result[tag], ensure_ascii=False), flush=True)

result["delta"] = {
    "delta_p_Pa_change_frac": (DP["t600"]["delta_p_Pa"] - DP["t400"]["delta_p_Pa"]) / DP["t400"]["delta_p_Pa"],
    "reached_outlet_change": result["t600"]["reasons"].get("reached_outlet", 0)
                             - result["t400"]["reasons"].get("reached_outlet", 0),
    "speed_median_change_frac": (result["t600"]["speed"]["median"] - result["t400"]["speed"]["median"])
                                / result["t400"]["speed"]["median"],
}
(HERE / "compare_t400_t600.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")

# ---- 并排三维对照图（同视角同种子，matplotlib 仅用于对照，不作定量证据）
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DengXian", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

fig = plt.figure(figsize=(13.5, 5.8), dpi=150)
for i, tag in enumerate(("t400", "t600")):
    ax = fig.add_subplot(1, 2, i + 1, projection="3d")
    for l in traced[tag]:
        p = l["pts_mm"]
        ax.plot(p[:, 0], p[:, 1], p[:, 2], lw=0.6,
                color="#2a9d4a" if l["reason"] == "reached_outlet" else "#b64e43", alpha=0.75)
    ax.view_init(azim=-60, elev=30)
    r = result[tag]["reasons"]
    ax.set_title("%s · Δp %.4f Pa\n共 %d 条 · 抵达出口 %d · 出域 %d · 滞留 %d"
                 % (tag, DP[tag]["delta_p_Pa"], result[tag]["n_lines"],
                    r.get("reached_outlet", 0), r.get("exited_wall_region", 0),
                    r.get("stall_near_wall", 0)), fontsize=10)
    ax.set_xlabel("x mm", fontsize=8); ax.set_ylabel("y mm", fontsize=8); ax.set_zlabel("z mm", fontsize=8)
    ax.tick_params(labelsize=7)
fig.suptitle("同一收敛 case（t042_b15_wssfix，b15 maxh1）· 同种子 60/侧 · vtkStreamTracer\n"
             "绿=抵达鼻咽出口 红=未抵达", fontsize=11)
fig.tight_layout()
fig.savefig(HERE / "compare_t400_t600.png", bbox_inches="tight")
print("写出 compare_t400_t600.png", flush=True)

# ---- t600 交互 HTML（vtk 引擎版）
context = {
    "title": "三维流线 · 腔内速度与静压（收敛终态 time=600）",
    "crumb": "鼻腔 CFD 工作台 · 患者流场演示 <b>t042_b15_wssfix</b>",
    "sub": "WSL t042_b15_wssfix（b15 maxh1，S-A 预设）· time index 600 · 1,161,194 四面体",
    "badges": [("", "工程屏通过（T-042 M2 四判据）"), ("", "未临床复核")],
    "honesty_summary": "工程屏通过但非临床结果 · 后处理级流线 · 未经人体复核 · 坐标未归位",
    "honesty": [
        "该场 Time=600 正常 End，T-042 记录 M2 四判据全过（Δp 10.294 Pa 入带 / 不平衡 5.27e-7 / "
        "monitor 0.0089% / 不崩）；但仍是<b>层流、未过 N6 解剖门</b>的工程试算场，"
        "此图<b>不能用于临床结论</b>；",
        "流线由 vtkStreamTracer（ParaView 内核）追踪，属<b>后处理级</b>；"
        "定量一律以 postProcessing 的 <code>surfaceFieldValue</code> 为准；",
        "未见人体复核：<code>clinical_status: generalisation_test_only_no_human_review</code>；",
        "坐标尺为<b>求解器坐标</b>（mm），未做 LPS/解剖方位归位，x/y/z 不等于「左右/前后/上下」。",
    ],
    "stats": [
        ("Δp（600）", "10.294 Pa", "postProcessing 锚点"),
        ("Δp（400）", "10.294 Pa", "差 0.001%"),
        ("抵达鼻咽出口", "%d / %d 条" % (result["t600"]["reasons"].get("reached_outlet", 0),
                                      result["t600"]["n_lines"]),
         "占 %d%%" % round(100 * result["t600"]["reasons"].get("reached_outlet", 0)
                          / result["t600"]["n_lines"])),
        ("沿流线速度中位", "%.2f m/s" % result["t600"]["speed"]["median"],
         "max %.2f" % result["t600"]["speed"]["max"]),
    ],
    "facts": [
        ("来源", "WSL <code>t042_b15_wssfix</code> · time index <code>600</code>（收敛终态）"),
        ("网格", "<code>b15_patient_maxh1_repaired.msh</code> · 1,161,194 四面体"),
        ("工况", "双鼻孔各 1.25e-4 m³/s（15 L/min，固定 50:50）· 出口 p=0 gauge"),
        ("口径", "T-006/T-041 口径，<b>不可与 T-021/T-029 混用</b>"),
        ("数值验证", "工程屏四判据过（T-042 记录）；残余未达 residualControl 严格收敛"),
        ("临床状态", "<code>generalisation_test_only_no_human_review</code>"),
    ],
    "footnote": "vtkStreamTracer（ParaView 内核）追踪；种子两侧鼻孔面各 60 个（同 T-044 种子序列）。"
                "400/600 对照见 compare_t400_t600.json（T-049）。",
}
f600 = fields["t600"]
meta600 = {"n_lines": result["t600"]["n_lines"], "reasons": result["t600"]["reasons"]}
html = render_html(f600, traced["t600"], meta600, context)
(HERE / "streamlines_t600.html").write_text(html, encoding="utf-8")
(HERE / "streamlines_t600_meta.json").write_text(
    json.dumps({**result["t600"], "lines": [{k: v for k, v in l.items()
               if k not in ("pts_mm", "spd", "pPa")} for l in traced["t600"]]},
               ensure_ascii=False, indent=2), "utf-8")
print("写出 streamlines_t600.html / meta", flush=True)
