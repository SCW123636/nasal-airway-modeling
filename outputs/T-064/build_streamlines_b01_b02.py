# -*- coding: utf-8 -*-
"""
T-064 · b01/b02 解剖斜切扩展域流线补齐（不重跑模拟，从 T-058 已算好的 t600 场追踪）
输入：本目录 vtk_b01/t600、vtk_b02/t600（WSL t058_chain_anat/<case>/foam_maxh1/VTK 只读拷贝，
      chain 第 9 步 foamToVTK -ascii 产物）
口径：与 T-057/T-049/T-058 同引擎（vtkStreamTracer）、同种子（seed=7，每侧 60 种子）。
Δp 锚点 = T-058 metrics（postProcessing ×ρ1.2）：
  b01 15.460361 Pa（轴位切 T-047 对照 15.709，−1.59% 切面口径差）
  b02 43.230504 Pa（首产基线，无轴位切对照）
产出：streamlines_<case>_anat_t600.html / .lines.json / view png / meta json
"""
import base64
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "work" / "lib"))
from flow_streamlines import (classify_endpoints, extract_field,  # noqa: E402
                              render_html, trace_lines_vtk)

HERE = Path(__file__).resolve().parent
OUTLET = "oropharynx_truncation_outlet"

CASES = {
    "b01": {
        "dp_ext": 15.460361239424284, "dp_axial": 15.709, "dp_axial_src": "T-047（历史轴位切口径）",
        "cells_checkmesh": "710,101", "cells_netgen": "696,358",
        "outlet_mesh": "210.60", "outlet_opening": "208.46", "outlet_axial": "148.93（T-047）",
        "volume_mm3": "27,534.1",
    },
    "b02": {
        "dp_ext": 43.230504459526095, "dp_axial": None, "dp_axial_src": "",
        "cells_checkmesh": "590,961", "cells_netgen": "573,555",
        "outlet_mesh": "85.45", "outlet_opening": "84.57", "outlet_axial": "91.98（退役轴位切，唯一方向相反例）",
        "volume_mm3": "21,127.7",
    },
}


def b64(arr):
    return base64.b64encode(np.ascontiguousarray(arr).tobytes()).decode("ascii")


def write_lines_json(case, field, lines, dp_src):
    """lines.json（T-063 schema），供 t058_cut / t058_cmp 叠加流线层。LPS mm。"""
    allspd = np.concatenate([l["spd"] for l in lines])
    allp = np.concatenate([l["pPa"] for l in lines])
    allpts = np.concatenate([l["pts_mm"] for l in lines] + [field["wall_pts"] * 1000.0])
    bmin, bmax = allpts.min(axis=0), allpts.max(axis=0)
    payload = {
        "schema": "nasal-streamlines-lines-v1",
        "case": case,
        "extracted_from": "T-064 直接由追踪结果序列化（源 HTML 同批生成，同源同口径）",
        "source_field": case + " 解剖斜切扩展域 t600 场（T-058 产物），vtkStreamTracer，seed=7 每侧 60",
        "units": "LPS mm（与 t058_*.json 模型同坐标系同单位；显示变换由页端做）",
        "delta_p_pa_src": dp_src,
        "clinical_status": "generalisation_test_only_no_human_review",
        "n_lines": len(lines),
        "meta": {
            "spd_p2": float(np.percentile(allspd, 2)), "spd_max": float(allspd.max()),
            "p_p2": float(np.percentile(allp, 2)), "p_max": float(allp.max()),
            "bbox": {"x": [round(float(bmin[0]), 1), round(float(bmax[0]), 1)],
                     "y": [round(float(bmin[1]), 1), round(float(bmax[1]), 1)],
                     "z": [round(float(bmin[2]), 1), round(float(bmax[2]), 1)]},
        },
        "lines": [{"side": l["side"], "reason": l["reason"], "length_mm": l["length_mm"],
                   "pos": b64(l["pts_mm"].astype(np.float32)),
                   "spd": b64(l["spd"].astype(np.float32)) if l.get("spd") is not None else None}
                  for l in lines],
    }
    out = HERE / ("streamlines_%s_anat_t600.lines.json" % case)
    out.write_text(json.dumps(payload), encoding="utf-8")
    print("写出", out.name, "（%.2f MB，%d 条）" % (out.stat().st_size / 1e6, len(lines)), flush=True)


def build(case):
    cfg = CASES[case]
    vtk = HERE / ("vtk_%s" % case) / "t600"
    print("== 提取 + 追踪（%s 解剖斜切扩展域）" % case, flush=True)
    field = extract_field(vtk, outlet=OUTLET)
    lines = trace_lines_vtk(vtk, n_seed=60, seed=7)
    core = classify_endpoints(field, lines, outlet=OUTLET)
    lens = [l["length_mm"] for l in lines]
    dp_ext = cfg["dp_ext"]

    result = {
        "task": "T-064 %s anatomical-oblique extended domain streamlines (backfill from T-058 field)" % case,
        "domain": "extended（鼻+鼻咽+可见口咽，出口 = oropharynx_truncation_outlet ▸ 解剖斜切⊥局部气道轴）",
        "engine": "vtkStreamTracer (ParaView kernel, RK45 + solver-grade interpolation)",
        "seed": 7, "n_seed_per_side": 60,
        "n_lines": core["n_lines"], "reasons": core["reasons"],
        "speed_mps": core["speed_mps"], "n_points_total": core["n_points_total"],
        "length_mm": {"median": float(np.median(lens)), "max": float(max(lens)),
                      "p10": float(np.percentile(lens, 10))},
        "delta_p_Pa": dp_ext,
        "delta_p_axial_Pa": cfg["dp_axial"],
        "source_vtk_dir": str(vtk.resolve()),
        "clinical_status": "generalisation_test_only_no_human_review",
    }
    print(json.dumps({k: v for k, v in result.items() if k not in ("task",)}, ensure_ascii=False), flush=True)

    # ---- 静态对照视图（matplotlib 仅呈现，不作定量证据）
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
    ax.set_title("%s 解剖斜切扩展域 t600 · Δp %.3f Pa\n共 %d 条 · 抵达口咽出口 %d · 出域 %d · 滞留 %d"
                 % (case, dp_ext, core["n_lines"], r.get("reached_outlet", 0),
                    r.get("exited_wall_region", 0), r.get("stall_near_wall", 0)), fontsize=10)
    ax.set_xlabel("x mm", fontsize=8); ax.set_ylabel("y mm", fontsize=8)
    ax.set_zlabel("z mm", fontsize=8); ax.tick_params(labelsize=7)
    fig.suptitle("%s 口咽扩展域 · 解剖斜切（T-058，%s cells）· 同种子 60/侧 · vtkStreamTracer\n"
                 "绿=抵达口咽截断出口 红=未抵达" % (case, cfg["cells_checkmesh"]), fontsize=11)
    fig.tight_layout()
    fig.savefig(HERE / ("view_%s_anat.png" % case), bbox_inches="tight")
    plt.close(fig)
    print("写出 view_%s_anat.png" % case, flush=True)

    # ---- 交互 HTML
    n_reach = core["reasons"].get("reached_outlet", 0)
    axial_stats = (("Δp（轴位切对照）", "%.3f Pa" % cfg["dp_axial"],
                    cfg["dp_axial_src"] + " · 切面口径差非修正"),) if cfg["dp_axial"] else ()
    axial_note = ("；轴位切（%s）为历史口径，二者 Δp %.3f vs %.3f Pa 属切面口径差，<b>不是修正</b>"
                  % (cfg["dp_axial_src"], dp_ext, cfg["dp_axial"])) if cfg["dp_axial"] else \
                 "；本例<b>首次进入求解链</b>（无轴位切对照基线，T-058 值即首产基线）"
    context = {
        "title": "三维流线 · 腔内速度与静压（%s 扩展域 · 解剖斜切，time=600）" % case,
        "crumb": "鼻腔 CFD 工作台 · 患者流场 <b>%s · 口咽扩展域 · 解剖斜切（T-058 场 / T-064 补追踪）</b>" % case,
        "sub": "WSL t058_chain_anat/%s（maxh1，S-A 预设）· time index 600 · %s 单元（checkMesh）"
               % (case, cfg["cells_checkmesh"]),
        "badges": [("", "工程屏通过（T-058 M2 四判据）"), ("", "未临床复核")],
        "honesty_summary": "工程屏通过但非临床结果 · 后处理级流线 · 未经人体复核 · 坐标未归位",
        "honesty": [
            "该场 Time=600 正常 End，T-058 记录 M2 四判据全过（Δp <b>%.3f Pa</b> 入带 / 不崩）；"
            "但仍是<b>层流、工程试算场</b>，此图<b>不能用于临床结论</b>；" % dp_ext,
            "出口切面口径 = <b>解剖斜切</b>（⊥局部气道轴；用户 2026-10-16 裁定「按照人体构造来就好，斜切」）；"
            "出口帽 <b>%s mm²</b>（mesh 阶段）/ %s mm²（开口阶段）%s；"
            % (cfg["outlet_mesh"], cfg["outlet_opening"], axial_note),
            "出口为口咽底<b>工程截断面</b>（<code>oropharynx_truncation_outlet</code>），<b>缺下咽-喉下游阻力</b> → "
            "Δp 偏低估方向已知；",
            "流线由 vtkStreamTracer（ParaView 内核）追踪，属<b>后处理级</b>；"
            "定量一律以 postProcessing 的 <code>surfaceFieldValue</code> 为准；",
            "未见人体复核：<code>clinical_status: generalisation_test_only_no_human_review</code>；",
            "坐标尺为<b>求解器坐标</b>（mm），未做 LPS/解剖方位归位，x/y/z 不等于「左右/前后/上下」。",
        ],
        "stats": [
            ("Δp（解剖斜切）", "%.3f Pa" % dp_ext, "T-058 postProcessing 锚点"),
        ] + list(axial_stats) + [
            ("抵达口咽出口", "%d / %d 条" % (n_reach, core["n_lines"]),
             "占 %d%%" % round(100 * n_reach / max(core["n_lines"], 1))),
            ("沿流线速度中位", "%.2f m/s" % core["speed_mps"]["median"],
             "max %.2f" % core["speed_mps"]["max"]),
        ],
        "facts": [
            ("来源", "WSL <code>t058_chain_anat/%s/foam_maxh1</code> · time index <code>600</code>（T-064 补追踪，未重跑模拟）" % case),
            ("域", "<b>扩展域</b>（鼻+鼻咽+可见口咽）· 出口 <code>oropharynx_truncation_outlet</code> %s mm²（mesh）" % cfg["outlet_mesh"]),
            ("网格", "%s 单元（checkMesh）· %s tet（netgen）" % (cfg["cells_checkmesh"], cfg["cells_netgen"])),
            ("工况", "双鼻孔各 1.25e-4 m³/s（15 L/min，固定 50:50）· 出口 p=0 gauge"),
            ("口径", "T-006/T-041/T-042/T-047/T-054/T-058 口径，<b>不可与 T-021/T-029 混用</b>"),
            ("追踪口径", "同 T-057/T-049/T-058（vtkStreamTracer，seed=7，每侧 60 种子）→ 与 b15 可比"),
            ("临床状态", "<code>generalisation_test_only_no_human_review</code>"),
        ],
        "footnote": "vtkStreamTracer（ParaView 内核）追踪；种子两侧鼻孔面各 60 个（同 T-044/T-049/T-057/T-058 种子序列）。"
                    "定量 meta 见 T-064 meta json。",
    }
    meta = {**core, **{k: v for k, v in result.items()
                       if k in ("task", "domain", "delta_p_Pa", "clinical_status", "seed", "n_seed_per_side")}}
    html = render_html(field, lines, meta, context, outlet=OUTLET)
    (HERE / ("streamlines_%s_anat_t600.html" % case)).write_text(html, encoding="utf-8")
    (HERE / ("meta_%s_anat.json" % case)).write_text(
        json.dumps({**result, "lines": [{k: v for k, v in l.items() if k not in ("pts_mm", "spd", "pPa")}
                                        for l in lines]}, ensure_ascii=False, indent=2), "utf-8")
    print("写出 streamlines_%s_anat_t600.html / meta_%s_anat.json" % (case, case), flush=True)
    write_lines_json(case, field, lines, "T-058 metrics_t058_%s_oroext.json（postProcessing ×ρ1.2）" % case)


if __name__ == "__main__":
    for case in (sys.argv[1:] or ["b01", "b02"]):
        build(case)
