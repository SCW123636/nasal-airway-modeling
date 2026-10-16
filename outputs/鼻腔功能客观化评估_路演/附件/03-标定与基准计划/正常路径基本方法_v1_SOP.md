# 鼻腔 CFD 表面制备 — 正常路径基本方法（v1）

> 范围：**正常状况**。异常/特殊状况（p0 类点位异常、序列不可用、几何自相交等）
> 本文档**不处理**，另立文档。本方法的目标是让正常例**无人值守跑通**。

## 0. 什么叫「正常状况」

一条数据只有当下面 **6 条全满足** 时才适用本方法。任何一条不满足即转人工通道，
**不在本文档范围内**。

| # | 条件 | 判据 |
|---|---|---|
| N1 | 有可用轴位原始序列 | `ImageType` 含 `ORIGINAL` + `AXIAL`，in-plane ≤ 0.8 mm |
| N2 | 分割三标签非空 | `nasal_cavity_left/right`、`nasopharynx` 体素数 > 0 |
| N3 | 空气腔非空 | 三标签并集 ∩ HU < −300 后体素数 > 0 |
| N4 | 表面闭合 | marching cubes 后 `boundary_edges == 0` |
| N5 | 自动提案可用 | 三开口有可用 `point_lps_mm` + `normal_lps`；`status` 见 §0.1 |
| N6 | 开口面积入带 | 鼻孔 ∈ [40,140] mm²、鼻咽出口 ∈ [120,500] mm² |

27 例新数据中，**24 例（b01–b24）满足 N1**（单一干净序列）；
b25/b26/b27 是多序列例，**不属于本文档范围**。

## 0.1 ⚠️ N5 的 `needs_review` 不是真正的阻塞（2026-10-12 定案）

**首次全批（b01–b24）结果：auto_pass 仅 2/24，22 例全部同因 `no_planes`，
detail 恒为同一句** —— 不是 22 种失败，是**一条判据把 22 例一起挡了**。

**真因**：`auto_anatomy_landmarks.py:433` 的 `fov_truncated_labels`，定义为
「标签掩膜任一体素触及 CT 立体六面之一即 True」；第 468 行据此把
`nasopharynx_outlet` 从 `proposed` 降级为 `needs_review`。

**该判据是「必要条件被当成充分条件」**（与 `surface_contact_audit.py` 同类错误）：

| 实测 | 值 | 含义 |
|---|---|---|
| `oropharynx` 触边 | **24/24** | 口咽本就向下延伸出扫描范围 → 判据恒真 |
| `soft_palate` 触边 | **22/24** | 全部触**头侧（superior）面** —— 颈部长度扫描里软腭就在 FOV 上界 |
| 未触边的两例 | b01 / b11 | **恰好就是通过的那两例** |

**点位本身完全不受影响**（24/24 实测）：

| 指标 | needs_review 组 (n=22) | proposed 组 (n=2) |
|---|---|---|
| `point_lps_mm` 存在 | 22/22 | 2/2 |
| 平面 RMS | 0.00–0.41 mm | 0.38 / 0.34 mm |
| 到软腭距离 | 4.95–11.68 mm | 5.74 / 6.43 mm |

两组分布**完全重叠，无区分力** → 该标志对点位质量**零信息量**。

**为什么试点 5 例没暴露**：同一条判据在 p0–p3 上已经触发 **3/5 次**
（p1 / p3 / p3t1），但旧路径走的是**人工复核过的点位**，完全绕开提案关卡。
走自动路径后 22/24 立即暴露。→ **这不是「新数据泛化差」，是旧路径掩盖了坏判据。**

**处置（不放宽阈值）**：新增显式开关 `--allow-needs-review`（默认关），
且**每个被放行的标志都记进报告的 `admitted_needs_review`**，不静默覆盖。
默认路径行为**逐字未变**（复验：p1/p3/p3t1 仍阻塞，p2 仍通过）。
判据修复（改测「结构被切断」而非「触碰边界」）列入待办，**不在本轮改**。

### 加 flag 后全批结果（2026-10-12）

| | 首跑（无 flag） | 加 flag |
|---|---|---|
| auto_pass | **2 / 24** | **18 / 24** |
| `no_planes` | 22 | **1** |

18 个通过的例，鼻侧 80.21–117.79 mm²、出口 250.01–444.79 mm²，**全部入带**。
b01 面积 80.12 / 83.33 / 299.43 mm² —— 与首跑**逐位一致**（flag 未改物理量）。

**6 例仍升级，且原因各异（这是有效信号，不是判据坏了）**：

| 例 | 原因 | 判读 |
|---|---|---|
| b20 | `no_planes`：`nostril_L status=unavailable` | **真·无点位**（「T300 下无有限接触面/向外通道」），非 FOV 标志 → 应拒绝 ✅ |
| b04、b23 | `onset_outlier`（−7.25 / −5.00 mm，带 [−4, 1]）+ `seed_lost` | 出口腔 onset 偏离五例观察带 → 需人工确认 |
| b05、b15、b18 | `seed_lost`（出口） | ROI 对该平面失效 → 需人工确认 |
| b04 | 另含 `nostril_L seed_lost` | 同上 |

→ **6 例全部是「本方法设计上就该转人工」的情形**，而非判据缺陷。

> ⚠️ **2026-10-13 更新**：上表为 **onset 起点（历史臂）** 的结果。默认搜索起点已改为
> `reviewed`（§2⑤），同批复跑为 **21/24**：b05/b15/b18 的 `seed_lost` 消失并转
> `auto_pass`，b04/b23 保留 `onset_outlier`、b20 保留 `no_planes`。
> 再加 `--allow-onset-outlier`（§0.2，opt-in）为 **22/24**：仅 b23 新增通过，
> b04 的理由由 `onset_outlier` 更正为真因 `seed_lost`；**通过例面积逐位未变**。
> 当前默认路径仍为 **21/24**，22/24 是 opt-in 臂。
> 有效数字以 §0.2 / §4 / §5 与 `normal_run_reviewed2.json` / `normal_run_onset_flag.json`
> 为准，**上表仅作历史对照**。

## 0.2 `onset_outlier` 门降级为顾问标记（2026-10-13，opt-in）

**背景**：`onset_outlier` 把「开口截面**总面积**首次达 50 mm² 的位置落在带 [−4, +1] mm 之外」
当成硬阻塞。该带宽取自**五例试点**，它守的是**以 onset 为锚**的放置搜索。

**为什么它已不再承重**：2026-10-13 起搜索起点默认改为 `reviewed`（§2⑤），
onset **不驱动任何位置**——它既不参与 `base`，也不参与二分窗口。

**A/B 实测**（`work/lib/probe_onset_gate_bypass.py`：同输入、同 `--search-origin reviewed`，
只切换 onset 门）：

| 例 | 门开（stock） | 门关 |
|---|---|---|
| b15 / b18 | auto_pass | **逐位相同**（80.04/80.06/439.18；80.09/80.07/251.64）|
| b23 | escalated `onset_outlier` | **auto_pass** 87.97/80.45/**276.87**（全在带内；出口仅位移 +0.45 mm）|
| b04 | escalated `onset_outlier` | escalated **`seed_lost`**（nostril_L + 出口）← **真实失败理由** |

三条读数：① 门对 onset 在带内的例**严格 no-op**（`elif` 分支不进入，代码路径完全相同）；
② b23 被门挡住，但其 reviewed 锚点搜索**能到带内面积**；③ b04 去掉门后**仍升级**，
理由从 `onset_outlier` 换成真正起作用的 `seed_lost`。
→ **该门在此批次从未提供安全性，只做「阻塞」与「误标」。**

**处置（opt-in，默认路径逐字未变）**：新增 `--allow-onset-outlier`
（`auto_opening_pipeline.py` / `nasal_pipeline.py`）。置位时越带 onset 记入报告
`onset_flags`（**观测信息不丢**），由放置自身门禁（`seed_lost` / `clip_failed` /
`gate_failed` / 面积带）决定成败。`no_onset`（±30 mm 内找不到任何 ≥50 mm² 截面）
**仍是硬阻塞**——那是「无可用几何」，不是起始位置偏好，与本节结论无关。

**为什么是 opt-in 而非改默认**：2026-10-13 曾把「保留为硬阻塞」写成决定，理由是
「去掉它等于用未知换通过」。**该理由对本批 b23 已被证伪**（它不是「未知」，而是
可核验的带内放置）；但改变对外基准仍需用户裁定，故先提供开关并记录两条臂的数字。

### 全批实测（`normal_run_onset_flag.json`，b01–b24，2026-10-13）

**auto_pass 22/24**（基线 `normal_run_reviewed2.json` 为 21/24）。

对账（`work/lib/ab_compare_runs.py`）：

| 判据 | 结果 |
|---|---|
| 基线 21 个通过例，面积**逐位相同** | ✅ 21/21（证明门对带内例是严格 no-op）|
| 新失败（通过 → 升级） | **0** |
| b23 | escalated → **auto_pass** 87.97/80.45/276.87 ✅ 符合预期 |
| b04 | 仍 escalated，理由从 `onset_outlier` → **`seed_lost`** ✅ 真因浮出 |
| b20 | 仍 escalated `no_planes` ✅ |

→ 仍然只有 2 例升级（b04 真·种子丢失 + b20 真·无点位），**与本节结论完全一致**。

### ⚠️ 工具自身曾误报（第 6 次同类事故，2026-10-13）

`ab_compare_runs.py` 原先把 `ANCHOR_FAILED = {b04, b23}` **连理由一起硬编码**，
前提是「两者都是锚点失败（onset_outlier）」。本次改造推翻的**正是这个前提**，
于是工具把一次正确的变更判成 `verdict: FAIL` ——**判据输出合法但与事实不符**，
正是本项目反复踩的那一类（阈值量纲错 / `area>=0` 恒真 / ImageType 索引猜错 /
基准值跨管线混记 / 弱证据布尔误判）。

**处置**：把「臂无关不变量」与「臂相关预期」分开——
前者（面积逐位一致、不得新失败）恒检；后者改为命令行参数
`--expect-pass` / `--expect-blocked` / `--reasons-clean`，不再内嵌个案结论。
**验证**：不带参数仍复现 `FAIL`（证明闸门未被放宽）；带
`--expect-pass b23 --reasons-clean b04` 得 `PASS`。

## 1. 五步链路（标准流程）

```
① 选序列      batch27_series_choice.py    →  每例一个 DICOM 目录
② 分割        ts_nasal_seg.py --batch-dir →  ct.nii.gz + masks/*.nii.gz
③ 提案        auto_anatomy_landmarks.py   →  landmarks.json（自动解剖点位）
④ 建表面      batch27_surface.py          →  source_surface.vtp
⑤ 开口定位    auto_opening_pipeline.py    →  逐例报告 + auto_placed.vtp
```

单一入口：`python nasal_pipeline.py --cases b01 b02 ...`（见 §4 验收后可用）。

## 2. 各步判据与参数（全部已实测，非拟合）

### ② 分割
- 任务 `head_glands_cavities`，CPU 约 136 s/例，只取三标签。
- 阈值 −300（与试点管线一致）。−350/−400 属验证任务，不在本方法内静默改。

### ③ 提案
`auto_anatomy_landmarks.py` 产出的三点位 **仅供作起点**，不是临床结论。

### ④ 建表面
- **三标签并集，再 ∩ HU < −300**。
  这一刀去掉 TotalSegmentator 在骨壁上纳入的部分容积体素；不做会明显更厚更糙。
- MC 在体素空间做，再套完整 LPS 仿射（复用生产函数 `mask_surface`）。

### ⑤ 开口定位（**v2 判据：按 cap 面积二分**）
沿平面法向二分，直到**生产 `clip_and_cap` 实际产出的端盖面积**达到解剖目标：

| 开口 | 目标 | 成人参考 |
|---|---|---|
| 鼻孔 L / R | **80 mm²** | 50–100 |
| 鼻咽出口 | **250 mm²** | 150–400 |

- 三开口**坐标下降**，≤3 轮（实测第 2 轮即收敛，末轮位移 0.0 mm）。
- 每开口 9 次二分；**窗口按搜索起点分档**：`onset` 14 mm / 2⁹ ≈ 0.027 mm，
  `reviewed` 3 mm / 2⁹ ≈ 0.006 mm。
- **搜索起点默认 `reviewed`（2026-10-13 起）**：从 landmark 阶段提出的平面
  （= 解剖锚点，王湧瑞 25/25 accept）出发，只有该处 cap 不足目标时才位移。
  `onset` 保留为对照臂（`--search-origin onset`）。

**为什么默认起点从 `onset` 改成 `reviewed`（2026-10-13 实测）：**
`onset` 是 `detect_onset` 判据的副产物——「截面**总面积**首次达 50 mm²」的位置
（`auto_opening_placement.py` 的 `AREA_ON = 50`），而 cap 目标是 80/250，**相差 5 倍**。
ROI 盒随平面一起平移，盒沿法向的负侧储备实测只有 **~1.15 mm**，于是任何
`|onset| ≳ 1.25 mm` 的开口在搜索起点处**盒内零种子**：

| 实测（b15 出口，push = 相对复核点位位移） | seeds | cap |
|---|---|---|
| 0.00 mm | 832 | **439.18**（带内） |
| −1.00 mm | 10 | 6.9 |
| −1.25 mm | **0** | FAIL |

`onset` 起点下 b05/b15/b18 全部 `seed_lost`；改 `reviewed` 起点后三例全部
`auto_pass` 且面积在带内（见 §5 表）。临界边界实测落在 push ∈ (−1.25, −1.00)：
b16/b21（onset −1.25，push −0.75）在界内通过，b15（push −1.25）在界外失败，
**两者只差 0.5 mm**。

**锚点超带的显式降级**：若 reviewed 平面自身 cap 已超 band 上限（实测仅 b08：
出口 772.35 > 500），则回退 `onset` 起点并在报告写 `origin_downgrade`
（含 reason 与违规面积），**不静默换起点**。b08 降级后 254.71，与 onset 基线逐位相同。

**为什么不直接用 onset：**
v1 以「截面总面积」为被控量，该量**有偏**——p1 鼻孔处端盖面积 85.95 mm²
竟大于整张截面 70.4 mm²，数学上不可能。v2 改用生产 cap 面积，绕开该问题。

## 3. 已知且必须转人工的两类

本方法**不覆盖**，仅列出以便识别：

- **p0 类**：出口面高于鼻孔面（p0/p1/p3 高 3.2–7.8 mm），连通域 flood 找不到负侧种子。
  已排除 ROI 平移解释，属复核点位问题，**非代码问题**。
- **多序列例**：b25/b26/b27 含 3D 重建、Dose Report、Scout 等。

## 4. 验收

正常例通过 = N1–N6 全满足，且报告 `decision == "auto_pass"`。

**⚠️ 本报告一律带 `clinical_status: generalisation_test_only_no_human_review`**。
自动通过 ≠ 临床可用。位置正确性只能由复核确认；本判据只保证**开口面积合理**。

### 已验证
- 试点 5 例（人工复核）：4/5 自动通过，位置距人工位 **0.00–1.42 mm**。
- 新数据 b01：**auto_pass**，面积 80.12 / 83.33 / 299.43 mm²，全在带内。
  ⚠️ 该数为 **onset 起点**（历史臂）产物；reviewed 起点下 b01 = 80.08 / 80.08 / 251.73。
- 新数据全批 **b01–b24（加 `--allow-needs-review`）**：
  - **onset 起点（历史臂，2026-10-12）：18/24 auto_pass**（见 §0.1）。
  - **reviewed 起点（2026-10-13 起为默认）：21/24 auto_pass**。
    新增通过 b05 / b15 / b18（原 `seed_lost`），**newly failing = 0**；
    保持报错 3 例：b04/b23 `onset_outlier`、b20 `no_planes`。
  6→3 例的升级原因全部属于「设计上应转人工」或「锚点本身不合法」的情形。

### 运行命令（正常批）
```
python work/lib/nasal_pipeline.py --skip-series \
  --jobs 2 --threads 6 --load-ceiling 78 --allow-needs-review
```
`--jobs 2 --threads 6 --load-ceiling 78` 为实测定案：全批 peak 42% / mean 36%（24 核机）。
搜索起点无需传参（默认 `reviewed`）；对照臂加 `--search-origin onset`。

### 溯源指纹（2026-10-13 补，改任何判据后复验时必读）

run JSON 现在为每例记录**本run实际产出的几何指纹**：`s3_propose.landmarks_sha256`、
`s4_surface.surface_sha256`，并与 s5 报告里它自报读过的 `plane_source_sha256` /
`source_sha256` **交叉核对**（`N6.provenance`，取值 `match` / `MISMATCH` / `unrecorded`）。

**任一 MISMATCH → 该例直接 escalated**，面积照记但不作为证据。

为什么值得单列一条：2026-10-13 追查 b02 出口 268.51 → 177.44 时，run 记录只有
rc/s/tail，无法回答「这批到底读了哪份 surface」；而每例详细报告会被后续批次覆盖，
不能当耐久记录。**没有指纹，跨批次对账只能靠猜。**

## 5. 基准值（改任何判据后必须先复验）

| 基准 | 值 | 出处 | 搜索起点 |
|---|---|---|---|
| 序列可选出 | ≥ 24 / 27 | `batch27_series_choice.json` | — |
| p2 出口 cap 面积 | **441.87 mm²** | `C:/ts_work/auto_opening_v2_20261011/p2.json` | onset（历史） |
| p1 鼻孔 cap 面积 | **80.07 mm²**（左） | `C:/ts_work/auto_opening_v2_20261011/p1.json` | onset（历史） |
| b01 出口 cap 面积 | **251.73 mm²** | `normal_run_reviewed2.json`（2026-10-13） | **reviewed（默认）** |
| b15 出口 cap 面积 | **439.18 mm²** | 同上 | reviewed |
| b18 出口 cap 面积 | **251.64 mm²** | 同上 | reviewed |
| b05 出口 cap 面积 | **252.27 mm²** | 同上 | reviewed |
| b08 出口 cap 面积 | **254.71 mm²** | 同上（经 `origin_downgrade` 回退 onset） | onset（降级后） |
| b23 出口 cap 面积 | **276.87 mm²** | `normal_run_onset_flag.json`（**仅加 `--allow-onset-outlier` 时**） | reviewed |

**上表后四行由 `python work/lib/print_run_table.py <run.json>` 从 run 文件直接生成，
禁止手抄**——本项目「基准值跨管线混记」事故的根因就是手抄。

⚠️ **默认臂与 opt-in 臂的关系**：b01–b22/b24 的数值在两条臂下**逐位相同**（已用
`ab_compare_runs.py` 验证 21/21 bit-identical）；差异**仅**为两条记录：
b23 从 escalated 变 **auto_pass**（上表末行），b04 的理由由 `onset_outlier` 更正为
真因 `seed_lost`。所以**不需要两套基准表**——默认臂用本表，opt-in 臂在本表基础上
多一条 b23。

onset 历史臂下的同批数值（供对照，**勿混用**）：b01 出口 299.43 / b08 出口 254.71；
b05 / b15 / b18 在 onset 臂为 `seed_lost`，**无面积值**（这正是默认起点被改掉的原因）。

### ⚠️ 勘误（2026-10-12）
本表此前误记为「p2 出口 292.13 / p1 鼻孔 85.95」。**这两个数字不属于 v2 管线**，
它们是 **ROI-box / 选择谓词时代（`connectivity_opened_20261011`）的固定平面面积**——
那个时代不做面积目标二分，p2 出口恰好落在 292.13。

v2 改按 cap 目标二分后，p2 出口 = **441.87**、p1 鼻孔 = **80.07**。
差异**不是回归**：`source_sha256` 与原始 v2 产物逐位相同，实为**我把两条不同管线的数
混记成了一条基准**。

**教训**：基准值必须**带出处**（文件路径 + 管线名），否则跨管线改名后就会
拿旧管线的数去验新管线，得出假失败。

**缘由**：本项目已多次出现「判据/解析代码自身坏掉但输出看起来合法」
（自相交 det 阈值、`refine` 写 `area>=0`、DICOM `ImageType` 索引猜错、
基准值跨管线混记）。**任何新判据落地，先用已知答案验一遍，且已知答案要带出处。**
