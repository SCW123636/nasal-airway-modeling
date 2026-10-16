# -*- coding: utf-8 -*-
"""s1_norm.py —— S1 队列常模计算（v0.1：G 层 n=24 有效子集 + C 层 n=3 切片）。

纪律（训练设计 §4 + 有依据设计 §5.1）：
- 只报 median/IQR/分位数/min/max + 有效 n；**不做正常/异常判定**
- 锚点层（E1）永不并入队列估计——单独一列，见 profile.py 的 C-b 句式
- 被 QC 门排除的例：记账（excluded 列表带原因），不静默丢弃
- 绝对值不可对标临床鼻测压（C4）；跨例比较只用同协议相对量
"""

from __future__ import annotations

import numpy as np

from . import MODEL_VERSION, SCHEMA_VERSION


def _midrank_percentile(values: list[float], v: float) -> float:
    arr = np.asarray(values, dtype=float)
    n = arr.size
    below = int(np.sum(arr < v))
    equal = int(np.sum(arr == v))
    return round(100.0 * (below + 0.5 * equal) / n, 1)


def feature_norm(rows: list[dict], feature: str) -> dict:
    """对一个特征算队列统计。只用 qc.in_norm 的行。"""
    vals, cases = [], []
    for r in rows:
        if not r["qc"].get("in_norm", False):
            continue
        v = r["features"].get(feature)
        if v is None:
            continue
        vals.append(float(v))
        cases.append(r["case"])
    if not vals:
        return {"feature": feature, "n": 0, "cases": [], "note": "无有效值"}
    arr = np.asarray(vals)
    out = {
        "feature": feature,
        "n": int(arr.size),
        "cases": cases,
        "median": round(float(np.median(arr)), 6),
        "q1": round(float(np.percentile(arr, 25)), 6),
        "q3": round(float(np.percentile(arr, 75)), 6),
        "min": round(float(arr.min()), 6),
        "max": round(float(arr.max()), 6),
    }
    out["per_case_percentile"] = {
        c: _midrank_percentile(vals, float(v)) for c, v in zip(cases, vals)
    }
    return out


def layer_norm(rows: list[dict], layer: str, feature_names: list[str]) -> dict:
    lrows = [r for r in rows if r["layer"] == layer]
    excluded = [
        {"case": r["case"], "reason": r["qc"].get("exclude_reason")}
        for r in lrows if not r["qc"].get("in_norm", False)
    ]
    return {
        "layer": layer,
        "schema": SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "conventions": lrows[0]["conventions"] if lrows else None,
        "n_total": len(lrows),
        "excluded": excluded,
        "features": {f: feature_norm(lrows, f) for f in feature_names},
    }


def norm_all(g_rows: list[dict], c_rows: list[dict],
             g_features: list[str], c_features: list[str]) -> dict:
    return {
        "G": layer_norm(g_rows, "G", g_features),
        "C": layer_norm(c_rows, "C", c_features),
    }
