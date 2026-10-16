# -*- coding: utf-8 -*-
"""evidence.py —— 证据登记表加载与校验（B1 数字三件套 / B3 分层显式）。

登记表是标准模型症状/锚点陈述的唯一事实源：报告里每条 E1/E2 引用
必须带登记表 ID；加载时校验必填字段，缺字段 = 登记表不合格 = 不许用。
"""

from __future__ import annotations

import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parent / "data" / "evidence_registry.json"

REQUIRED_FIELDS = ("id", "layer", "metric", "value", "citation",
                   "strength", "transfer", "used_for", "review")
# direction（关联方向）只对 E2 有意义；E1 锚点/E3 操作化假设显式写 n/a
REQUIRED_BY_LAYER = {"E2": ("direction",)}


def load_registry(path: Path | None = None) -> dict:
    p = path or REGISTRY_PATH
    with open(p, encoding="utf-8") as f:
        reg = json.load(f)
    errors = []
    for e in reg.get("entries", []):
        for k in REQUIRED_FIELDS:
            if k not in e:
                errors.append(f"{e.get('id', '?')}: 缺字段 {k}")
        for k in REQUIRED_BY_LAYER.get(e.get("layer"), ()):
            if k not in e:
                errors.append(f"{e.get('id', '?')}: 缺字段 {k}（{e.get('layer')} 必填）")
        if e.get("layer") not in ("E1", "E2", "E3"):
            errors.append(f"{e.get('id', '?')}: layer 非法 {e.get('layer')}")
    if errors:
        raise ValueError("证据登记表不合格:\n" + "\n".join(errors))
    return reg


def by_id(reg: dict, entry_id: str) -> dict:
    for e in reg["entries"]:
        if e["id"] == entry_id:
            return e
    raise KeyError(f"登记表无此 ID: {entry_id}")


def anchors(reg: dict) -> list[dict]:
    """E1 锚点（S1 锚点列 / C-b 句式用）。"""
    return [e for e in reg["entries"] if e["layer"] == "E1"]


def associations(reg: dict) -> list[dict]:
    """E2 文献关联（S4 映射层用；只转译方向，禁数值迁移）。"""
    return [e for e in reg["entries"] if e["layer"] == "E2"]


def counterexamples(reg: dict) -> list[dict]:
    """反例（strength=反例，必进每份 S4 报告附录，B6）。"""
    return [e for e in reg["entries"] if e.get("strength") == "反例"]
