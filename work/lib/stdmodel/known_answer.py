# -*- coding: utf-8 -*-
"""known_answer.py —— 已知答案验证器（B2：判据先过已知答案，CI 化）。

项目硬约束 3 的工程落地：所有判据/提取器先用「带出处的已知答案」验证，
逐位不过 → 退出码非零 → 不许进特征表。本项目已 7 次出现「判据输出合法
但与事实不符」，本模块把纪律变成自动门。

夹具来源（全部带出处）：
- T-058 三例全链汇总裁决（outputs/T-058/anat_chain_verification.json，
  2026-10-16 11:39，M2 六项×3 全 pass + 鼻孔回归×3 全 match）
- T-043 Graetz 合成验证（outputs/T-043/graetz_verification.json，
  平面通道温度场解析对账，残差 9.76e-13）——热通量提取器（v0.2）的夹具
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path("D:/项目/鼻腔建模")

# 容差：面积类 0.01 mm²（鼻孔回归门同款）；sha 逐位；其余 rel 1e-9
TOL_AREA_MM2 = 0.01
TOL_REL = 1e-9

# T-058 anat_chain_verification.json 的权威值（汇总裁决，2026-10-16 11:39）
FIXTURES_T058 = {
    "b15": {
        "nostril_L_mm2": 80.03741, "nostril_R_mm2": 80.057289,
        "outlet_opening_mm2": 125.845838,
        "delta_p_pa": 17.119542030795298, "resistance_pa_s_ml": 0.06847816812318118,
        "wss_force_n": 0.00148545062118494, "wss_median_pa": 0.06777372384868408,
        "mesh_cells": 653789,
        "source": "outputs/T-058/anat_chain_verification.json#b15",
    },
    "b01": {
        "nostril_L_mm2": 80.082608, "nostril_R_mm2": 80.081077,
        "outlet_opening_mm2": 208.460364,
        "delta_p_pa": 15.460361239424284, "resistance_pa_s_ml": 0.06184144495769712,
        "wss_force_n": 0.0012736585187948888, "wss_median_pa": 0.05025978813342112,
        "mesh_cells": 710101,
        "source": "outputs/T-058/anat_chain_verification.json#b01",
    },
    "b02": {
        "nostril_L_mm2": 80.149521, "nostril_R_mm2": 80.224047,
        "outlet_opening_mm2": 84.572528,
        "delta_p_pa": 43.230504459526095, "resistance_pa_s_ml": 0.17292201783810435,
        "wss_force_n": 0.0023701889127586465, "wss_median_pa": 0.08971002711026776,
        "mesh_cells": 590961,
        "source": "outputs/T-058/anat_chain_verification.json#b02",
    },
}

# T-043 Graetz 合成验证（热通量/温度提取器 v0.2 夹具；v0.1 只登记不跑）
FIXTURE_GRAETZ = {
    "outlet_temperature_k": 306.1499997,
    "residual": 9.76e-13,
    "source": "outputs/T-043/graetz_verification.json",
}

AREA_KEYS = ("nostril_L_mm2", "nostril_R_mm2", "outlet_opening_mm2")


def check_case(case: str, actual: dict) -> list[str]:
    """把实际提取值与夹具逐项比对，返回不一致清单（空 = 过）。"""
    fx = FIXTURES_T058.get(case)
    if fx is None:
        return [f"{case}: 无夹具（只验有已知答案的例）"]
    bad = []
    for k, expected in fx.items():
        if k == "source":
            continue
        if k not in actual or actual[k] is None:
            bad.append(f"{case}.{k}: 实际缺失")
            continue
        got = actual[k]
        if k in AREA_KEYS:
            if abs(got - expected) > TOL_AREA_MM2:
                bad.append(f"{case}.{k}: 实际 {got} vs 已知 {expected} (Δ={got-expected:+.6f})")
        else:
            denom = abs(expected) if expected else 1.0
            if abs(got - expected) / denom > TOL_REL:
                bad.append(f"{case}.{k}: 实际 {got} vs 已知 {expected}")
    return bad


def gate(cases_actual: dict[str, dict]) -> tuple[bool, list[str]]:
    """CI 门：全部夹具例逐位过 → True。不过 → 调用方必须退出，不许出模型。"""
    problems: list[str] = []
    for case in FIXTURES_T058:
        problems += check_case(case, cases_actual.get(case, {}))
    return (len(problems) == 0), problems


def load_t058_verification() -> dict:
    p = ROOT / "outputs/T-058/anat_chain_verification.json"
    with open(p, encoding="utf-8") as f:
        return json.load(f)
