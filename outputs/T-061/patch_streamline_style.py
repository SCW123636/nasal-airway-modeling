# -*- coding: utf-8 -*-
"""把已生成的流线产物 <style> 段替换为模板同款（配色统一为工作台令牌）。

背景：流线 HTML 由 work/lib/flow_streamlines.py + work/lib/assets/streamlines_template.html
生成。模板配色已换，但已落盘的两份产物（pro/artifacts/streamlines_b15_*）若重生成需要
WSL 原始 case 数据；本脚本只就地替换样式段，**不动任何数据/脚本内容**，并逐份校验
「除 <style> 外的正文 sha256 不变」。

用法：python patch_streamline_style.py            # 干跑，只报告
      python patch_streamline_style.py --apply    # 实际写盘
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / 'work/lib/assets/streamlines_template.html'
TARGETS = sorted((ROOT / 'work/07_cfd_pipeline/workspace/pro/artifacts').glob('streamlines_*.html'))
STYLE_RE = re.compile(r'<style>.*?</style>', re.S)


def split(html: str):
    m = STYLE_RE.search(html)
    if not m:
        raise SystemExit('未找到 <style> 段')
    return html[:m.start()], html[m.end():], m.group(0)


def main() -> int:
    apply = '--apply' in sys.argv
    new_style = split(TEMPLATE.read_text(encoding='utf-8'))[2]
    for path in TARGETS:
        text = path.read_text(encoding='utf-8')
        head, tail, old_style = split(text)
        if old_style == new_style:
            print(f'[跳过] 已是新配色 {path.name}')
            continue
        before = hashlib.sha256((head + tail).encode()).hexdigest()
        out = head + new_style + tail
        n_head, n_tail, _ = split(out)
        after = hashlib.sha256((n_head + n_tail).encode()).hexdigest()
        old_green = sum(old_style.count(c) for c in ('#257861', '#23332f', '#edf5f0', '#ecd9b0', '#f5f7f5'))
        new_green = sum(new_style.count(c) for c in ('#257861', '#23332f', '#edf5f0', '#ecd9b0', '#f5f7f5'))
        print(f'{path.name}: 正文 sha256 不变 = {before == after}；旧绿色字面量 {old_green} → {new_green}')
        if before != after:
            raise SystemExit('正文被改动，已中止')
        if apply:
            path.write_text(out, encoding='utf-8')
            print(f'  已写盘 {path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
