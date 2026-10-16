# -*- coding: utf-8 -*-
"""profile.py —— 每例剖面卡渲染（C-a 队列事实 / C-b 锚点偏离，句式模板化）。

禁句（有依据设计 §4）：不输出「该患者 ENS6Q≈X」「正常/异常」「高于文献
阈值故异常」。症状侧陈述一条都不产（v0.1 无症状标签层；S4 映射层属 v0.2）。
"""

from __future__ import annotations

from .evidence import anchors


def _fmt(v, nd=3):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}".rstrip("0").rstrip(".")
    return str(v)


def anchor_deviations(row: dict, reg: dict) -> list[str]:
    """C-b 句式：只对 v0.1 有对应锚点的特征（MCA ↔ AR 带）产出，且必带
    「量级哨兵非合格线」口径。其余锚点（后鼻孔 T/RH 等）v0.1 无对应特征，不产出。"""
    out = []
    if row["layer"] != "G":
        return out
    a5 = next((a for a in anchors(reg) if a["id"] == "E1-A5"), None)
    if not a5:
        return out
    ref_cm2 = 0.75  # 亚洲成人（measure_mca LITERATURE.asian_adult_mca_cm2）
    for side in ("L", "R"):
        v = row["features"].get(f"mca_{side}_mm2")
        if v is None:
            continue
        ratio = (v / 100.0) / ref_cm2
        flag = row["qc"]["mca_entry_artifact_flag"].get(side)
        src = row["qc"]["mca_source"].get(side)
        note = f"（取值={src}，入口伪影待核）" if flag else ""
        out.append(
            f"- **MCA{side}**：{_fmt(v,1)} mm² = {v/100:.3f} cm²，对 AR 文献亚洲成人参考 "
            f"0.75±0.03 cm² 的比值 **{ratio:.2f}×**{note} —— C-b 锚点偏离："
            f"「AR 与 CT 在体位/黏膜状态/起点定义上系统性有偏，只作量级哨兵，非合格线」"
            f"（{a5['id']} {a5['citation']}）"
        )
    return out


def render_case_markdown(row: dict, norm: dict, reg: dict) -> str:
    case, layer = row["case"], row["layer"]
    ln = norm[layer]
    feats = row["features"]
    qc = row["qc"]
    n_layer = ln["n_total"]
    excluded = [e for e in ln["excluded"]]

    lines = [
        f"# 标准模型剖面 · {case}（{layer} 层）",
        "",
        f"- schema：`{row['schema']}` ｜ clinical_status：`{row['clinical_status']}`",
        f"- 口径六元组：domain={row['conventions']['domain']}；cut={row['conventions']['cut']}；"
        f"bc={row['conventions']['bc']}；threshold={row['conventions']['threshold']}；"
        f"numerics={row['conventions']['numerics']}；convergence={row['conventions']['convergence']}",
        f"- 输入指纹：surface/opening/metrics 等 sha256 见特征行 JSON（行级可追）",
        "",
    ]
    if layer == "C":
        lines += [
            f"**⚠ n=3 切片**：CFD 层当前仅 b15/b01/b02 三例（T-058 已验证），"
            f"下表百分位为三例切片内相对位置，**不是队列常模**；24 例 CFD 层阻塞于 D-0 口径裁定。",
            "",
        ]
    if not qc.get("in_norm", False):
        lines += [
            f"**⛔ 该例未进常模**（QC 门：{qc.get('exclude_reason')}）——以下仅报该例原始值，不进任何队列统计。",
            "",
        ]

    lines += ["## 一、队列百分位（C-a：队列事实）", "",
              "| 特征 | 该例值 | 单位 | 队列中位 | IQR | 切片内百分位 |", "|---|---|---|---|---|---|"]
    for f, stat in ln["features"].items():
        if f not in feats or feats[f] is None:
            continue
        pct = stat.get("per_case_percentile", {}).get(case, "—") if stat.get("n") else "—"
        unit = _unit(f)
        lines.append(
            f"| {f} | {_fmt(feats[f])} | {unit} | {_fmt(stat.get('median'))} | "
            f"{_fmt(stat.get('q1'))}–{_fmt(stat.get('q3'))} | {pct} |"
        )
    n_eff = next(iter(ln["features"].values())).get("n") if ln["features"] else 0
    lines += ["", f"（队列 n_total={n_layer}，进常模有效 n={n_eff}；"
              + (f"排除：{excluded}" if excluded else "无排除") + "）", ""]

    dev = anchor_deviations(row, reg)
    lines += ["## 二、文献锚点偏离（C-b：对 E1 锚点，不作正常/异常判定）", ""]
    lines += dev if dev else ["（v0.1 该层无对应锚点特征）", ""]

    lines += [
        "## 三、口径与边界", "",
        "- 本卡只报**队列百分位**与**锚点偏离**；正常/异常判定不做（归复核人口径）。",
        "- 绝对值不可对标临床鼻测压（C4）；跨例比较只用同协议相对量。",
        "- 症状侧零标签：本卡不含任何症状陈述。",
        "",
    ]
    if layer == "C":
        lines += [
            "## 四、CFD 收敛状态（B7 诚实性口径）", "",
            f"- converged={qc.get('converged')}；numerical_validation={qc.get('numerical_validation')}；"
            f"mass_imbalance={qc.get('mass_imbalance_frac')}",
            f"- M2 判据：{qc.get('m2_criteria')}",
            "",
        ]
    return "\n".join(lines)


_UNITS = {}


def _unit(f: str) -> str:
    from .schema import FEATURES
    return FEATURES.get(f, {}).get("unit", "")
