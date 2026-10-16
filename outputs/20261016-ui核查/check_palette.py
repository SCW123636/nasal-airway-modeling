# -*- coding: utf-8 -*-
"""工作台配色审计：校验「工作台表面集」内所有 chrome 均为中性色。

表面集（surface）定义：从 `/workspace/pro/index.html` 出发，经其自身外壳、
中栏四 tab、顶栏两个跳转，以及 `/` 遗留工作台外壳及其 03/06 步面板，可到达的
全部 HTML/CSS/JS。

判据
    - 逐个颜色算通道极差 (max-min)。统一令牌下 chrome 极差 ≤ 2；阈值取 **> 8**，
      可捕获细微蓝/绿偏移（如 #dbe4e9、#e9efff）。
    - 豁免：① 白色及白色透明；② **画布数据色**（三维几何配色、流场色带、图表
      数据系列），按文件显式列入 DATA_KEEP —— 这是 tokens.css 纪律第 2 条
      唯一允许用色的场景。
    - vendor/、artifacts/（构建产物另由 patch_streamline_assets.py 单独校验）不扫。

报告分三段：表面集校验结果 / 数据色豁免清单 / 未纳入表面集的遗留页（信息性）。

用法：python check_palette.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(r"D:/项目/鼻腔建模")
WS = ROOT / "work" / "07_cfd_pipeline" / "workspace"
LIB = ROOT / "work" / "lib"

# ---- 工作台表面集 ------------------------------------------------------------
SURFACE = [
    WS / "pro" / "index.html", WS / "pro" / "pro.css", WS / "pro" / "pro.js",
    WS / "pro" / "tokens.css",
    WS / "t058_cut.html", WS / "t058_cut.js",
    WS / "t058_cmp.html", WS / "t058_cmp.js",
    WS / "progress-cards.html",
    WS / "workspace.css", WS / "embedded.css", WS / "workbench-pro.css",
    WS / "index.html", WS / "workspace.js",
    WS / "boundary-review" / "index.html",
    WS.parent / "viewer" / "viewer.css", WS.parent / "viewer" / "viewer.js",
    ROOT / "work" / "进度总览.html",
    LIB / "assets" / "streamlines_template.html",
    LIB / "assets" / "streamlines_app.js",
]
# 表面集内的数据色白名单（画布几何分类色 / 流场色带 / 三维标注；一律 `#rrggbb` 小写，
# 脚本会把 JS 里的 `0xrrggbb` 折算成同形比对）
DATA_KEEP = {
    # 三维几何分类色：壁面 / 鼻开口 L / 鼻开口 R / 出口帽 / 切除楔形
    "t058_cut.html": {"#1f77b4", "#2ca02c", "#e8823a", "#d62728", "#c3cdda"},
    "t058_cmp.html": {"#1f77b4", "#2ca02c", "#e8823a", "#d62728", "#c3cdda"},
    # 同上 + 新切面 / 轴位切面标注
    "t058_cut.js": {"#1f77b4", "#2ca02c", "#e8823a", "#d62728",
                    "#c3cdda", "#c96a1e", "#8a9390"},
    "t058_cmp.js": {"#1f77b4", "#2ca02c", "#e8823a", "#d62728",
                    "#c3cdda", "#c96a1e"},
    # 流线页：壁面 / 开口 / 楔形 / 坐标尺线框
    "streamlines_template.html": {"#1f77b4", "#2ca02c", "#d62728", "#8d9bab", "#c3cdda"},
    "streamlines_app.js": {"#1f77b4", "#2ca02c", "#d62728", "#8d9bab", "#c3cdda"},
    # 遗留查看器：viridis 速度/静压色带
    "viewer.css": {"#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"},
    # 遗留查看器：网格材质 + 标定标记状态色（normal / needs_review 两态）
    "viewer.js": {"#70a9b6", "#285da0", "#395eb9", "#b87513", "#ffa12f"},
}
# 未纳入表面集的遗留页（信息性列出，不做判定）
OUT_OF_SURFACE = [
    ("work/06_auto_landmarks/index.html", "遗留工作台 04 步 切片审核（navy 系，模板/构建器生成）"),
    ("work/06_auto_landmarks/feedback_review/index.html", "遗留工作台 05 步 意见核对（同上）"),
    ("work/lib/feedback_review_template.html", "上述 05 步页的模板"),
    ("work/lib/medical_review_template.html", "医学复核页模板"),
    ("work/08_method_explanation/", "方法说明页（独立文档站）"),
    ("work/03_calib/鼻腔标定复核.html", "早期标定复核页（无服务路由）"),
    ("work/09_coarse_localization/pipeline_check/index.html", "粗定位自检页（无服务路由）"),
    ("work/10_nasalseg_intake/nasalseg_article.html", "分割说明文（独立文档）"),
    ("work/zenodo_13893419.html", "外部文献页面存档"),
    ("work/07_cfd_pipeline/workspace/upper-airway.*", "咽部扩展页（T-060 已移除入口）"),
    ("work/07_cfd_pipeline/优化空间与后续设计_云端调研委托_20261012.html", "独立调研委托报告"),
]

HEX = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F])")
HEX0X = re.compile(r"0x([0-9a-fA-F]{6})\b")
THRESHOLD = 8


def expand(h: str) -> str:
    if len(h) == 4:
        return "#" + "".join(c * 2 for c in h[1:])
    return h


def spread(h: str) -> int:
    h = expand(h)
    return (max(int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))
            - min(int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)))


def main() -> int:
    violations, missing, neutral, exempt = [], [], 0, []
    for p in SURFACE:
        if not p.is_file():
            missing.append(str(p.relative_to(ROOT)))
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        keep = DATA_KEEP.get(p.name, set())
        hits, kept = {}, []
        for m in HEX.finditer(text):
            lit = expand(m.group(0).lower())
            if lit.startswith("#ffffff"):
                neutral += 1
                continue
            if lit in keep:
                kept.append(lit)
                continue
            if spread(lit) > THRESHOLD:
                hits[lit] = hits.get(lit, 0) + 1
            else:
                neutral += 1
        for m in HEX0X.finditer(text):
            lit = "#" + m.group(1).lower()
            if lit in keep:
                kept.append("0x" + m.group(1).lower())
                continue
            if spread(lit) > THRESHOLD:
                hits[lit] = hits.get(lit, 0) + 1
            else:
                neutral += 1
        if kept:
            exempt.append({"file": str(p.relative_to(ROOT)), "data_colors": sorted(set(kept))})
        if hits:
            violations.append({"file": str(p.relative_to(ROOT)), "colors": sorted(hits)})

    print("=== 工作台表面集校验 ===")
    for v in violations:
        print(f"✗ {v['file']} → {len(v['colors'])} 种带色相：{v['colors']}")
    for m in missing:
        print(f"? 缺失（跳过）：{m}")
    print(f"表面集文件 {len(SURFACE) - len(missing)} 个；中性色 {neutral} 处")

    print("\n=== 画布数据色豁免（tokens.css 纪律第 2 条允许）===")
    for e in exempt:
        print(f"· {e['file']} → {e['data_colors']}")

    print("\n=== 未纳入表面集的遗留页（信息性，未判定）===")
    for path, why in OUT_OF_SURFACE:
        print(f"· {path} —— {why}")

    out = Path(__file__).resolve().parent / "palette_audit.json"
    out.write_text(json.dumps({
        "surface_files": len(SURFACE) - len(missing),
        "violations": violations, "missing": missing,
        "data_exemptions": exempt, "neutral_count": neutral,
        "threshold": THRESHOLD,
        "out_of_surface": [{"path": a, "why": b} for a, b in OUT_OF_SURFACE],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n写入", out)

    if violations or missing:
        print("✗ 表面集未通过")
        return 2
    print("✓ 表面集全部 chrome 为中性色；仅画布数据色有色相 —— 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
