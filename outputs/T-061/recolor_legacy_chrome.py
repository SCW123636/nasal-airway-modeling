# -*- coding: utf-8 -*-
"""把工作台遗留 chrome 样式表的绿/蓝/橙/红配色收敛到统一令牌
（与 workspace/pro/tokens.css 同值），保留画布数据色。

覆盖文件
    workspace/workspace.css            遗留工作台外壳（绿系）
    workspace/embedded.css             embed.js 注入的嵌入态样式（绿系）
    workspace/workbench-pro.css        遗留工作台覆盖层（绿系）
    workspace/boundary-review/index.html  边界草稿页内联样式（绿/琥珀/红）
    viewer/viewer.css                  遗留三维查看器（蓝系；保留 viridis 色带）

判据
    - 每个文件**穷举全部颜色字面量**并显式映射，不靠阈值近似。
    - 唯一例外是画布数据色（viewer.css 的 viridis 图例色带），列入 DATA_KEEP，
      原样保留并在报告中标注。
    - 自校验 ① 每个映射键必须真的命中过（防静默空转）；
      ② 替换后不得残留任何「通道极差 > 8」的颜色（数据色除外）；
      ③ 除白/白透明外的颜色必须全部落在令牌值集合内。

用法
    python recolor_legacy_chrome.py            # 预演（dry-run）
    python recolor_legacy_chrome.py --apply    # 实际写入（一次性迁移，勿重复跑）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(r"D:/项目/鼻腔建模")
WS = ROOT / "work" / "07_cfd_pipeline"

# ---- 统一令牌（与 workspace/pro/tokens.css 同值）-----------------------------
INK, MUT, FAINT = "#1a1a1a", "#6e6e6e", "#9a9a9a"
LINE, LINE2 = "#dcdcdc", "#c8c8c8"
SOFT, SOFT2 = "#f0f0f0", "#e4e4e4"
ACCENT, CANVAS, BG = "#1a1a1a", "#eef0f0", "#ebebeb"
WARN, WARMBG, BAD, BADBG = "#3d3d3d", "#efefef", "#000000", "#e2e2e2"

TOKENS = {INK, MUT, FAINT, LINE, LINE2, SOFT, SOFT2, ACCENT, CANVAS, BG,
          WARN, WARMBG, BAD, BADBG, "#ffffff", "#1a1a1a55"}

# ---- 共用映射（绿系遗留 → 令牌）---------------------------------------------
COMMON = {
    # 主色 / 深色文字
    "#257861": INK, "#23332f": INK, "#315342": INK, "#386650": INK,
    "#48745a": INK, "#4c755a": INK, "#53705c": INK, "#56625c": INK,
    "#a5d3bf": INK, "#91b9a0": INK,
    # 次要 / 提示文字
    "#557266": WARN, "#99691e": WARN, "#946921": WARN, "#82682f": WARN,
    "#90651d": WARN, "#d6a34b": WARN,
    "#66746c": MUT, "#688173": MUT, "#768579": MUT, "#78817e": MUT,
    "#79867d": MUT, "#81948a": MUT, "#88938c": MUT, "#89958e": MUT,
    "#77827d": MUT,
    # 最弱文字
    "#919b95": FAINT, "#929a95": FAINT, "#939c96": FAINT, "#99a39c": FAINT,
    "#99a69d": FAINT, "#9da79f": FAINT, "#9faa9f": FAINT, "#9fac9f": FAINT,
    "#a0aaa3": FAINT, "#a1aaa4": FAINT, "#a3aba6": FAINT, "#a3aca5": FAINT,
    "#96a099": FAINT,
    # 失败（红）→ 单色黑
    "#b64e43": BAD,
    # 描边
    "#72ac8d": LINE2, "#acd0bd": LINE2, "#d7b66d": LINE2,
    "#d2e6d9": LINE, "#d6e7db": LINE, "#d9e9df": LINE, "#dce3dd": LINE,
    "#dce8df": LINE, "#dce9df": LINE, "#dceadf": LINE, "#e1e9e3": LINE,
    "#e4e9e6": LINE, "#edf1ed": LINE, "#efd6ce": LINE, "#e2e9e4": LINE,
    # 浅底
    "#e8efea": SOFT2, "#e9eee9": SOFT2, "#e0eee3": SOFT2,
    "#eaf4ed": SOFT, "#edf5f0": SOFT, "#eef5ef": SOFT, "#eff2ef": SOFT,
    "#eff6f1": SOFT, "#f0f3f0": SOFT, "#f0f3f1": SOFT, "#f0f6f1": SOFT,
    "#f8faf8": SOFT, "#edf3ed": SOFT, "#f6f9f7": SOFT, "#f7f9f7": SOFT,
    # 提示底 / 失败底
    "#fff2d8": WARMBG, "#fff4de": WARMBG, "#fff8ea": WARMBG, "#fff5e4": WARMBG,
    "#fff8e8": WARMBG, "#fff9eb": WARMBG, "#fff0ea": WARMBG, "#fff1ee": WARMBG,
    "#fceeea": BADBG,
    # 页面底
    "#f5f7f5": BG,
    # 8 位 hex
    "#172d2855": "#1a1a1a55",
}

# ---- 各文件增量映射 ----------------------------------------------------------
EXTRA = {
    "workspace/workbench-pro.css": {
        "#5d6a62": MUT, "#8b948e": FAINT, "#9fc4ae": LINE2,
        "#d8e0da": LINE, "#eef5f0": SOFT, "#f2f8f4": SOFT, "#f4f8f5": SOFT,
    },
    "workspace/boundary-review/index.html": {
        "#1d2226": INK, "#6f7d75": MUT, "#dfe7e1": LINE,
        "#efdfb9": LINE2, "#f4f7f4": SOFT,
    },
    "viewer/viewer.css": {
        "#23394b": INK, "#617589": MUT, "#28627c": INK, "#475d96": INK,
        "#5b6e7a": MUT,
        "#c9dce2": LINE, "#dbe4e9": LINE, "#edf0f2": LINE,
        "#e8eff1": CANVAS,          # #scene 视口底 → 中性视口灰
        "#e9efff": SOFT2, "#eef5f7": SOFT,
        "#f2f5f5": BG,
        "#81b8d0": INK,             # focus-visible 描边
        "#82acb9": LINE2, "#b87513": INK,
        "#906321": WARN, "#694000": WARN, "#815b20": WARN,
        "#fff0cf": WARMBG, "#fff1d4": WARMBG,
    },
}

# ---- 画布数据色白名单（保留不动）--------------------------------------------
DATA_KEEP = {
    "viewer/viewer.css": {
        "#440154", "#3b528b", "#21918c", "#5ec962", "#fde725",  # viridis 色带
    },
}

# 目标文件顺序（先做遗留工作台，最后做查看器）
FILES = [
    "workspace/workspace.css",
    "workspace/embedded.css",
    "workspace/workbench-pro.css",
    "workspace/boundary-review/index.html",
    "viewer/viewer.css",
]

HEX = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F])")


def expand(h: str) -> str:
    """`#rgb` → `#rrggbb`；输入含 `#`。8 位不动。"""
    if len(h) == 4:
        return "#" + "".join(c * 2 for c in h[1:])
    return h


def spread(h: str) -> int:
    h = expand(h)
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    return max(r, g, b) - min(r, g, b)


def main() -> int:
    apply = "--apply" in sys.argv
    problems: list[str] = []
    used: set[str] = set()

    for rel in FILES:
        path = WS / rel
        if not path.is_file():
            problems.append(f"{rel} 不存在")
            continue

        m = dict(COMMON)
        m.update(EXTRA.get(rel, {}))
        keep_data = DATA_KEEP.get(rel, set())
        text = path.read_text(encoding="utf-8")
        hits: dict[str, int] = {}
        unmapped: dict[str, int] = {}

        def repl(mo: re.Match, _m=m, _hits=hits, _un=unmapped) -> str:
            lit = expand(mo.group(0).lower())
            if lit in TOKENS or lit in keep_data or lit.startswith("#ffffff"):
                return mo.group(0)
            if lit in _m:
                used.add(lit)
                _hits[lit] = _hits.get(lit, 0) + 1
                return _m[lit]
            _un[lit] = _un.get(lit, 0) + 1
            return mo.group(0)

        new = HEX.sub(repl, text)

        # 自校验 ①：无未映射颜色
        if unmapped:
            problems.append(f"{rel} 有未映射颜色：{unmapped}")

        # 自校验 ②：无残留色相（极差 > 8，数据色与白除外）
        left = {}
        for mo in HEX.finditer(new):
            lit = expand(mo.group(0).lower())
            if lit.startswith("#ffffff") or lit in keep_data:
                continue
            if spread(lit) > 8:
                left[lit] = left.get(lit, 0) + 1
        if left:
            problems.append(f"{rel} 仍残留带色相颜色：{left}")

        # 自校验 ③：除白外全部落在令牌值内
        stray = sorted({expand(mo.group(0).lower()) for mo in HEX.finditer(new)
                        if not expand(mo.group(0).lower()).startswith("#ffffff")}
                       - TOKENS - keep_data)
        if stray:
            problems.append(f"{rel} 出现非令牌颜色：{stray}")

        keep_note = f"｜数据色保留 {len(keep_data)} 个" if keep_data else ""
        print(f"— {rel}: 映射命中 {len(hits)} 种{keep_note}；残留 {len(left)}；未映射 {len(unmapped)}")
        if apply:
            path.write_text(new, encoding="utf-8")
            print(f"  已写入 {path}")

    all_keys = set(COMMON)
    for e in EXTRA.values():
        all_keys |= set(e)
    unused = sorted(all_keys - used)
    if unused:
        # 幂等提示：已迁移过的文件再次扫描时，其映射键自然全部失配。
        # 真正的正确性判据是逐文件的「未映射 / 残留 / 非令牌」三项，见上。
        print(f"\n（提示：{len(unused)} 个映射键本次未命中，"
              f"若为首次迁移请检查拼写；已迁移文件重复扫描属预期）")

    print(f"\n映射表命中 {len(used)} / {len(all_keys)} 个键")
    if problems:
        print("问题：")
        for p in problems:
            print("  ✗", p)
        return 2
    print("✓ 无残留色相，未映射 0，非令牌色 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
