
## T-061 工作台整体配色统一（2026-10-16 14:2x）

- **用户指令**：「你看一下整体配色之类的，我看还有的在沿用原来的，和现在的风格很不相符，你来更改」→ 立 **T-061**（T1 零 CPU 纯前端）。
- **单一真源**：新建 `work/07_cfd_pipeline/workspace/pro/tokens.css`（ink/muted/faint/line/line2/soft/soft2/accent/warn/bad/bg/panel/canvas/mono + 三纪律：chrome 单色 / 颜色只给数据 / 圆角 2–3px）。`pro/index.html` 于 `pro.css` 前引入；`pro/pro.css` 删自身 `:root`。
- **改动面**：`t058_cut.html/js`（视口底 `#e8eff1`→`#eef0f0`；3D 照明 `0xa9b9c0`→`0xc8c8c8`、坐标轴 `0x23332f`→`0x1a1a1a`）、`t058_cmp.html/js`、`streamlines_template.html` + `streamlines_app.js`（视口底 `0xeef3f1`→`0xeef0f0`；直方图柱 `#3b6ea5`→`#1a1a1a` / 轴 `#9aa7b4`→`#c8c8c8` / 刻度 `#5c6b7a`→`#6e6e6e`；坐标尺标签 `#33414f`→`#1a1a1a`）+ 两份已落盘流线产物（`outputs/T-061/patch_streamline_style.py` 与 `patch_streamline_assets.py`，正文 sha256 不变 + 每替换点恰好命中 1 次）、`build_progress_cards.py` / `build_progress_dashboard.py`（`:root` 换令牌；图例 emoji 换成**文字 + 单色底纹**；红底改灰底；圆角 10→3px）、`workspace.css` / `embedded.css` / `workbench-pro.css` / `boundary-review/index.html` / `viewer/viewer.css` / `viewer/viewer.js`（遗留工作台外壳与 03/06 步面板）。
- **迁移器** `outputs/T-061/recolor_legacy_chrome.py`：**一对一角色映射 80 个键**（穷举全部颜色字面量，不用阈值近似），自校验三项 = 未映射 0 / 残留色相 0 / 非令牌色 0。
- **表面集定义**：pro 外壳自身只链 `/progress/index.html`（顶栏进度总览）与 `/workspace/progress-cards.html`；而 `/progress/index.html` 被 `embed.js` 重定向到遗留工作台 `/workspace/index.html#overview`，其导航可达 `/viewer/`(03) 与 `/boundary-review/`(06) → 表面集 = 上述全部 + `/`，共 20 个前端文件。
- **按纪律保留（数据色）**：三维几何分类色（壁面 `#c3cdda` / 鼻开口 L `#1f77b4` / R `#2ca02c` / 出口帽 `#e8823a` / 楔形 `#d62728` / 新切面 `#c96a1e` / 轴位切面 `#8a9390`）、viewer 的 viridis 色带（`#440154 #3b528b #21918c #5ec962 #fde725`）与标定标记状态色（`#285da0` / `#b87513` / `#395eb9` / `#ffa12f`）、流线物理场色带与坐标尺线框 `#8d9bab`。
- **验收**：`outputs/20261016-ui核查/check_palette.py` → `palette_audit.json`（判据 = 通道极差 > 8 判带色相，可捕获 `#dbe4e9` / `#e9efff` 这类细微偏移；**违规 0**，中性色 368 处，退出码 0）；四组无头截图全零 pageerror（`shot_surfaces.py` / `shot_progress_full.py` / `check_progress_pages.py` ok=true / `shot_legacy.py`）。
- **记账**：**追认补卡第四次**（T-041、T-056、T-060 之后）——先执行后立约。卡 `tasks/T-061.md`、结论卡 `knowledge/结论卡/20261016-T-061-工作台整体配色统一.md`、`knowledge/索引.md` 已追加。
- **未决（T-062 候选）**：遗留复核工具链是否一并统一配色 —— `work/06_auto_landmarks/`（04 切片审核 / 05 意见核对）、`work/lib/feedback_review_template.html`、`work/lib/medical_review_template.html`、`work/08_method_explanation/` 方法说明页、`upper-airway.*`、无服务路由自检页、外部文献存档页、独立调研委托报告 HTML。理由 = 另一套 navy 系遗留工具链，模板 + Python 构建器生成，改了须重生成产物并跑自带测试。
