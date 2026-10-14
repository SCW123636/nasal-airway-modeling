# T-001-B findings · maxh 对照与 585 达标路径

> 专项对话 T-001-B（CPU 独占车道）。每跑完一步追加写入，防打断丢证据。
> 产物根：`C:\ts_work\mesh_tools\patient_mesh_20261013\t001b_maxh04\`（新建，未改既有文件）
> 输入 STL：`b15_patches_ascii.stl`（sha256 fbaf6234...，4 patch，与 maxh=1.0 同件）

---

## Step 1 · maxh=0.4 体网格生成（已完成）

**命令**（只改 `--maxh`，其余与 maxh=1.0 完全相同）：
```
wsl -d Ubuntu-22.04 bash -lc 'source /mnt/c/ts_work/mesh_tools/netgen_env.sh; cd /mnt/c/ts_work/mesh_tools/patient_mesh_20261013; export OMP_NUM_THREADS=6; python3 /mnt/d/项目/鼻腔建模/work/lib/netgen_patient_mesh.py b15_patches_ascii.stl b15_patches_ascii.export.json t001b_maxh04/b15_patient_maxh04.msh --maxh 0.4 --dump-arrays t001b_maxh04/b15_patient_maxh04.arrays.npz'
```
- 日志：`C:\ts_work\mesh_tools\patient_mesh_20261013\t001b_maxh04\netgen_maxh04.log`
- mesh.json：`...t001b_maxh04\b15_patient_maxh04.msh.mesh.json`

**同口径对照（maxh=1.0 vs maxh=0.4，仅 maxh 不同）**：

| 项 | maxh=1.0 | maxh=0.4 | 出处 |
|---|---|---|---|
| tetrahedra | 1,147,862 | **2,016,945** | `b15_patient_maxh1.msh.mesh.json` / `t001b_maxh04/b15_patient_maxh04.msh.mesh.json` |
| points | 224,589 | 373,494 | 同上 |
| grading | 0.1 | 0.1 | 同上（两版一致） |
| volume_m3 | 1.976894592371553e-05 | 1.9768945923715527e-05 | 同上（逐位一致，几何相同） |
| median_boundary_edge_mm | 0.548025 | 0.548025 | 同上（同一 STL） |
| patch 三角形数 | 5020/3431/17545/86822 | 5020/3431/17545/86822 | 同上（完全一致） |
| cap_area_deviation_pct | 2.518/1.371/11.042 | 2.518/1.371/11.042 | 同上（完全一致） |

→ 同口径成立：仅 maxh 由 1.0 降到 0.4，单元数 ×1.757，其余几何/标签全同。

**checkMesh（未修复）**：待 repair 完成后跑 gmshToFoam + checkMesh，求实 min det 与 <0.001 计数。

---

## Step 3 · 「8 个小行列式」出处（已结案：找到原文，但属圆管对照，非患者）

**结论：该数字真实存在，但来自「圆管/代理对照网格」，与患者体网格无关。旧记忆把跨管线/跨网格的结果混记到了患者身上。**

原文出处（已逐字核对）：
`C:\ts_work\mesh_tools\gmsh_trial\foam_netgen_g01\checkMesh.log`
- L99：`Cell determinant (wellposedness) : minimum: 0 average: 0.206704857093`
- L100：`***Cells with small determinant (< 0.001) found, number of cells: 8`
- L108：`Failed 1 mesh checks.`
- 该 case 单元数 `cells: 26887`（grep 命中），与 `cloud_summary_dl.md:939` 记载「Netgen maxh=0.4, grading=0.1，26,887 四面体，仍有 8 个小行列式单元」一致。

关联证据链：
- `C:\ts_work\mesh_tools\gmsh_trial\netgen_tube_strict.log:24`：`Invoked with: kwargs: maxh=0.4, grading=0.1, optsteps3d=3`（圆管对照的生成参数）。
- `D:\项目\鼻腔建模\.tools\cloud_summary_dl.md:939`：把 8 标为「当前最佳」的圆管对照结论。
- `D:\项目\鼻腔建模\.workbuddy\memory\2026-10-12.md:167`：「Netgen maxh=0.4 最优但仍有 8 个小行列式单元」。
- 同一记忆同段已写「**患者表面尚未复验**」——证成「8」从未指向患者网格。

**判定**：
1. 「8」有原始 checkMesh 日志支撑（foam_netgen_g01），非编造。
2. 但 26,887 单元 = 圆管对照几何；患者网格为 1.1M+（maxh=1.0）或 2.0M（maxh=0.4），二者量级与几何完全不同。
3. 患者网格在既往所有产物中**只跑过 maxh=1.0**（4548/585），从未在 maxh=0.4 跑过；所谓「患者 maxh=0.4 余 8」在本轮之前**无任何对应产物**。
4. 建议：从项目记忆/MEMORY 中删除「患者 maxh=0.4 余 8」这一表述，改为「圆管对照 maxh=0.4 余 8，患者未复验」（已由 knowledge/20261013 事实文件标注「疑似跨管线/跨网格混记」）。

---

## Step 2 · checkMesh（maxh=0.4，未修复 + 修复后）—— 已完成

**命令链**（仅 maxh 由 1.0 改为 0.4，其余同口径）：
```
# 修复（同口径）
python3 /mnt/d/项目/鼻腔建模/work/lib/repair_boundary_tetrahedra.py \
  t001b_maxh04/b15_patient_maxh04.msh t001b_maxh04/b15_patient_maxh04_repaired.msh
# OpenFOAM 转换 + 全检（native Linux FS，避 9p 卡死）
bash t001b_maxh04/run_foam_maxh04.sh   # gmshToFoam + checkMesh -allGeometry -allTopology
```
- 日志：`outputs/T-001/logs/checkMesh_maxh04_unrepaired.log`、`..._repaired.log`、`gmshToFoam_maxh04_*.log`

**同口径对照（maxh=1.0 vs maxh=0.4，同一 STL，仅 maxh 不同）**：

| 项 | maxh=1.0 未修复 | maxh=0.4 未修复 | maxh=1.0 修复后 | maxh=0.4 修复后 |
|---|---|---|---|---|
| cells | 1,147,862 | **2,016,945** | 1,161,194 | **2,028,003** |
| min cellDeterminant | 0 | 0 | 1.11163982652e-07 | **1.80188985973e-07** |
| `<0.001` 单元数 | 4,548 | **3,780** | 585 | **494** |
| 低插值权面 (<0.05) | 20 | 22 | 114 | 106 |
| gmshToFoam undefined faces | 112818 | 112818 | 112818 | 112818 |
| Failed checks | 2 | 2 | 2 | 2 |

- 出处：`outputs/T-001/logs/checkMesh.log`（maxh=1.0 修复后，已知基准）、`checkMesh_maxh04_unrepaired.log`、`checkMesh_maxh04_repaired.log`
- **结论**：maxh 降到 0.4 残余 sliver 数下降约 16%（未修复 4548→3780；修复后 585→494），但**远未清零（仍 494）**。maxh=0.4 仍报 `Failed 2`，患者网格在 maxh=0.4 下**不达标**，与旧记忆「maxh=0.4 余 8」完全不符（那 8 是圆管对照，见 Step 3）。

**修复副作用量化（maxh=0.4 是否同型）**：
- 方法：用 checkMesh 权威 `underdeterminedCells` set + 修复 json 的 `split_cell_indices`，按修复输出顺序映射判定每个 flagged 单元是「split 子单元（新造）」还是「原单元残留」。**不依赖本地 cellDeterminant 度量**（T-001-A 已证不可作判据）。
- maxh=1.0（来源 `b15_sliver_summary.json`）：585 中 **481 新造 / 104 原有**（82% 新造）
- maxh=0.4（来源 `outputs/T-001/repair_sideeffect_maxh04.json`）：494 中 **400 新造 / 94 原有**（81% 新造）
- **结论：同型**。中心细分消除「两外边界面」零行列式单元，但 ~81% 的残余 sliver 是细分新造的——修复策略在 maxh=0.4 上仍是**净负资产**（与 maxh=1.0 完全一致的副作用结构）。

---

## Step 4 · 候选对策排序（只排序，不真跑）

针对残余 585(→494 @maxh0.4) 个 `<0.001` 单元，按「代价/预期/治本程度」排序：

**1. Netgen 侧（几何治本，优先）**
- 1a. 曲率驱动细分（`segmentsperedge`↑ / `curvaturesafety`↑）：针对薄壁/狭缝/相切区的退化表面三角形（A4 已确认最短边 0.32/0.33 mm、最差质量 0.57），这是 sliver 源头。代价：改 Netgen 参数重跑（中等）。预期：直接减少继承的扁 tet，**正路，排序最高**。
- 1b. `optsteps3d`↑：单元质量优化。代价低（重跑）。预期：小幅改善，排序中（辅助 1a）。
- 1c. maxh 再降（0.4→0.2 更低）：代价高（单元数 ×~2+，内存/时间陡增；2M 已占大量内存）。参考圆管对照：`maxh 0.4→0.2 使 8→25`（密度增加反而恶化表面缺陷继承）。患者上 1.0→0.4 仅把残余从 585 降到 494，再降大概率无法清零且成本激增。**排序最低（性价比差）**。

**2. 修复侧（换策略，高优先但需另开卡实现）**
- 当前中心细分新造 ~81% sliver（maxh=0.4: 400/494），是负资产。候选替代：
  - 只对「原零行列式单元」细分（避免对好单元制造新 sliver）；
  - 或改用局部 sliver 去除（netgen `ImproveMesh` / 局部重剖分）；
  - 或仅对 flagged cells 邻域 refine。
- 代价：需改 `repair_boundary_tetrahedra.py`；**本卡硬约束不改 `work/lib/**`，故只能建议、不真跑**，应另开修复卡实现并复用本卡同口径 checkMesh 验证。
- 排序：高（治标且减副作用），但跨卡。

**3. 判据侧（不采纳放松阈值）**
- 阈值 0.001 是否过严？T-001-A 源码审计（`outputs/T-001/源码审计_cellDeterminant.md` 结论第 190 行）已定：该 metric 是 OpenFOAM **定制构建**的无量纲 wellposedness 度量（面面积各向异性归一化），本地 `cellDeterminant` 复算**不可作判据**（公式错 + 构建未知）；585/494 以 `checkMesh` stdout 为准。这些 flagged 单元是表面 sliver 传入的真实退化（扁平/零体积）单元，**非阈值假阳性**。
- 结论：**不应放松阈值**——放松会掩盖真实几何缺陷。判据侧无可行「达标」路径，达标须走几何/修复侧。
- 排序：不采纳。

**综合推荐路径**：1a（曲率驱动细分，治本）+ 2（换修复策略减副作用）并联；1c（再降 maxh）与 3（放松阈值）均不推荐。
