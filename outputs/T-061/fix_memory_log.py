# -*- coding: utf-8 -*-
"""修复 2026-10-16.md 末尾被 shell 反引号吞掉的 T-061 段落：
截断到 `## T-061` 之前，再追加 `memory_append.md` 的完整文本。
"""
import io
import sys
from pathlib import Path

LOG = Path(r"D:/项目/鼻腔建模/.workbuddy/memory/2026-10-16.md")
FRAG = Path(r"D:/项目/鼻腔建模/outputs/T-061/memory_append.md")

log = io.open(LOG, encoding="utf-8").read()
frag = io.open(FRAG, encoding="utf-8").read()

MARK = "## T-061"
i = log.find(MARK)
if i < 0:
    print("未找到 T-061 段落，无需修复")
    sys.exit(0)

head = log[:i].rstrip("\n")
frag = frag.lstrip("\n")
io.open(LOG, "w", encoding="utf-8").write(head + "\n\n" + frag)
print(f"已修复：截断至 {i} 字符，追加片段 {len(frag)} 字符")
