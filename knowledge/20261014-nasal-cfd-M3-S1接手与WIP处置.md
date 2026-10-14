# 20261014-nasal-cfd · M3-S1 接手与 WIP 处置

> 结论卡（协议 templates/D）。作者：M3-S1 段主对话。日期：2026-10-14 深夜。
> 读者：未来任何需要了解「10-14 深夜换届时工作树发生了什么」的对话。

## 结论（L1）

1. **黑板上「并行会话 5 个改动文件」的记录被推翻**：它们不是并行会话的活跃 WIP，而是 **10-11/12 留下的无任务卡遗留**（文件 mtime 为证），共 4 项独立改动，已补单测后分 2 个 commit 归档为 WIP。
2. **现行管线曾完全裸露在 git 之外**：`nasal_pipeline.py` / `auto_opening_pipeline.py` 等 90 个文件（含 9 份权威文档）自 10-13 起一直未跟踪，已按 G6 保护性例外快照入库。
3. **`.gitignore` 有一个医疗数据漏洞已补**：`资料/副鼻窦27例_脱敏完整/`。
4. **M3 排期草案已就绪**，含成本结构与两道前置门选项表，待用户 checkpoint。

## 证据（L2，逐条标核验状态）

| # | 事实 | 核验状态 |
|---|---|---|
| 1 | 5 个改动文件 mtime 为 10-11 16:28 ~ 10-12 08:00，早于黑板 v2 重建（10-13） | 已核验（`ls -la`） |
| 2 | WIP 内容 = ① `solver/mesh_cache.py`（复用「输入未变+checkMesh 通过」网格，sha256 签名含真实表面/网格字典/后端身份）＋ phantom_validation/structured_split_feedback 两处拷贝接线 ② `ts_nasal_seg.py` CPU 亲和限核（实测：无限制占 24 核 35%、亲和 6 核 24.7%、`OMP_NUM_THREADS` 无效）③ `partitioned_surface.py` `clip_and_cap` 增 `selectors`（连通性掩码替代轴对齐 ROI 盒；None 时原行为逐字节不变）④ `dicom_sitk.py` 扩展名大小写不敏感匹配（`.dcm`/`.DCM` 混批修复，与已记 DICOM 硬坑一致） | 已核验（逐 diff 读过；`names` 变量在函数开头有定义，fallback 无潜伏 bug） |
| 3 | `test_mesh_cache.py` 11/11 过、`test_partitioned_surface.py` 6/6 过（nasal-cfd venv 直接跑，非 pytest） | 已核验（本次主对话复跑） |
| 4 | `git ls-files work/lib` 仅 159 个（10-12 前快照）；`nasal_pipeline.py`/`auto_opening_pipeline.py` 不在其中 | 已核验 |
| 5 | 未跟踪快照 90 文件 = 63 py + 18 json + 9 文档，最大 52K，无医疗数据（`资料/` 已全部 ignore） | 已核验（扩展名/大小清点） |
| 6 | `资料/副鼻窦27例_脱敏完整/` 未忽略时泄漏面 = 64 个 `__MACOSX/._*` 元数据垃圾（医学数据已被 `*.nrrd`/`*.dcm` 规则挡住） | 已核验（`git ls-files --others` 清点） |
| 7 | 36 格矩阵 = 3 阈值 × 2 几何 × 3 网格 × 2 求解；唯一网格 18 个；T-006 Run 1 ≈ 5.1 s/step × 500+ 步 | 已核验（引自 state/MEMORY 既有记录） |

## 采纳判断与落点（L3）

- **归档而非丢弃**：WIP 无任务卡、无端到端证据，但内容自洽且与项目硬约束（CPU≤80%）和 M3（网格缓存省一半建网格 CPU）直接相关 → 以 WIP 身份入库，commit 信息显式标注「未验证」，不冒充已验证能力。
- **快照而非审查**：90 文件未逐文件审查，commit 信息明示「快照非审查结论」；防的是丢失，不是认证。
- **不自行裁定两道门**：医学门涉外部复核人、adapter 门涉契约治理面 → 登记 R11/R12，呈用户 checkpoint。

## 交付物

- commit `6c28036`（.gitignore 补洞）/ `7d51232`（WIP①网格缓存，35 文件）/ `4db369f`（WIP②管线三改）/ `e317f0e`（90 文件快照）
- `plan/主计划.md` M3-S1 节（排期草案 + 门选项表 + 拟派卡编号）
- `state/状态.md` M3-S1 接手节 + R11/R12
- `C:\Users\lenovo\.workbuddy\project-files\nasal-cfd\PROJECT.md` §8 末行

## 状态增量

- **推翻**：黑板「并行会话 5 个改动文件」（实为无任务卡遗留 WIP，10-11/12）。
- **新发现**：网格缓存 WIP 与 M3 矩阵的量化关联（18 唯一网格 → 第 2 求解设置复用 → 省约一半建网格 CPU）。
- **新登记**：R11（医学门）/ R12（adapter 门），均待用户裁定。
- **未决**：M3 矩阵第三档 maxh 取值（建议 ≤0.2，需先核成本）；T-007 模板标定用户仍未派。
