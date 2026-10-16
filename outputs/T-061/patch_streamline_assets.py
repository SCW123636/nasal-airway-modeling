# -*- coding: utf-8 -*-
"""把已落盘的流线产物 HTML 里内联的 chrome 色收敛到统一令牌。

背景：`streamlines_*.html` 是自包含单文件产物 —— `streamlines_template.html` 的
样式段 + `streamlines_app.js` 的内联脚本。样式段此前已由
`patch_streamline_style.py` 收敛；本脚本处理**内联脚本**里的绘图 chrome 色
（坐标尺标签、长度分布直方图的柱/轴/刻度文字、3D 视口底）。

保留：物理场色带（脚本内的归一化 RGB stops 数组）、坐标尺线框 `0x8d9bab`
（三维标注层，属数据域）。

用法：python patch_streamline_assets.py [--apply]
"""
from __future__ import annotations

import sys
from pathlib import Path

ASSETS = Path(r"D:/项目/鼻腔建模/work/07_cfd_pipeline/workspace/pro/artifacts")
FILES = ["streamlines_b15_anat_t600.html", "streamlines_b15_oroext_t600.html"]

# (旧, 新) —— 每项必须在每个文件里恰好出现 1 次，否则判失败
SUBS = [
    ("0xeef3f1", "0xeef0f0"),      # 3D 视口底（原淡绿）→ 令牌 --canvas
    ("'#33414f'", "'#1a1a1a'"),    # 坐标尺标签 sprite（墨色）
    ("'#3b6ea5'", "'#1a1a1a'"),    # 长度分布直方图柱（单系列 → 单色）
    ("'#9aa7b4'", "'#c8c8c8'"),    # 直方图轴线
    ("'#5c6b7a'", "'#6e6e6e'"),    # 直方图刻度文字
]
# 必须保持不动的数据色
KEEP_DATA = ["0x8d9bab", "'#1f77b4'", "'#2ca02c'", "'#d62728'",
             "0x1f77b4", "0x2ca02c", "0xd62728"]


def main() -> int:
    apply = "--apply" in sys.argv
    problems = []
    for name in FILES:
        p = ASSETS / name
        if not p.is_file():
            problems.append(f"{name} 不存在")
            continue
        text = p.read_text(encoding="utf-8")
        report = []
        for old, new in SUBS:
            n = text.count(old)
            report.append(f"{old}×{n}")
            if n != 1:
                problems.append(f"{name}: {old} 出现 {n} 次（期望 1）")
                continue
            text = text.replace(old, new)
        kept = {k: text.count(k) for k in KEEP_DATA if text.count(k)}
        print(f"— {name}: " + " ".join(report) + f"｜数据色保留 {kept}")
        if apply:
            p.write_text(text, encoding="utf-8")
            print(f"  已写入 {p}")

    print()
    if problems:
        print("问题：")
        for x in problems:
            print("  ✗", x)
        return 2
    print("✓ 全部替换点唯一命中，数据色未动")
    return 0


if __name__ == "__main__":
    sys.exit(main())
