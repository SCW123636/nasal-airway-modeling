# T-001-A 源码审计 ｜ `checkMesh` 的 `cellDeterminant` 到底是哪个公式

> 模型自报原句：**You are powered by the model named Hy3.**
> 车道：只读 / 零 CPU。本文件为逐步追加的审计留痕，最终判决见 §4。
> 源码树：`C:\ts_work\mesh_tools\openfoam_source\openfoam-OpenFOAM-v1912.200626`（Build 头标注 `OPENFOAM=1912 patch=200626`，与日志一致）

---

## 0. 结论摘要（先看这里）

- `checkMesh` 报的 `cellDeterminant` **实际走的是 `polyMeshGeometry::checkCellDeterminant`**（`polyMeshGeometry.C:1989`），**不是** `primitiveMeshTools::cellDeterminant`（`primitiveMeshTools.C:456`，那是另一个库函数，本次 checkMesh 几何路径并未用它）。任务卡指引的 `primitiveMeshCheck.C` 里**根本没有** `cellDeterminant`。
- 该公式对单元用**全部面**、按面面积大小 **`|S_i|` 加权**构造并矢张量 `Σ |S_i|·(û_i û_iᵀ)`，再 `det(·/Σ|S_i|) ×27`，归一化到立方体=1。
- **关键障碍**：日志里的打印文本（`(wellposedness)` / `minimum: X average: Y` / `***Cells with small determinant (< 0.001) found, number of cells: N`）在所提供的整棵 v1912.200626 源码树中**一个字都搜不到**；源码里对应例程 `polyMeshGeometry::checkCellDeterminant` 打印的是 `"Cell determinant (1 = uniform cube) : average = ...  min = ..."`（`polyMeshGeometry.C:2047`）。→ **产生 `checkMesh.log` 的 `checkMesh` 是定制/打过补丁的构建**，其精确公式无法仅凭本源码树 100% 确认。
- 本地重建脚本的算法本身写错（见 §3），其 7.40e-08/575 等数字不是对任一标准公式的忠实复现。
- **判决（§4）：本地复算「不可作判据」，以 `checkMesh` 的 stdout 为准。**
- **`Failed 2 mesh checks` 的两项（§5）**：① Cell determinant (wellposedness) — 585 单元 <0.001；② Face interpolation weight (<0.05) — 114 face。

---

## 1. 源码定位（逐文件确认）

Grep `cellDeterminant` 全树，命中：

| 位置 | 性质 |
|---|---|
| `src/OpenFOAM/meshes/primitiveMesh/primitiveMeshCheck/primitiveMeshTools.C:456` | 库函数 `primitiveMeshTools::cellDeterminant`，返回 `scalarField`（**不是** checkMesh 本次走的通路） |
| `src/dynamicMesh/motionSmoother/polyMeshGeometry/polyMeshGeometry.C:1989` | `polyMeshGeometry::checkCellDeterminant`（7 参，**真正计算+打印**） |
| `src/dynamicMesh/motionSmoother/polyMeshGeometry/polyMeshGeometry.C:2337` | `polyMeshGeometry::checkCellDeterminant`（2 参重载，转发到 1989） |
| `applications/utilities/mesh/manipulation/checkMesh/checkGeometry.C:865` | `mesh.checkCellDeterminant(true, &cells)` —— **checkMesh 的调用点** |

调用链：`checkGeometry.C:865`（在 `if (allGeometry)` 块内）
→ `polyMeshGeometry.C:2337` 的 2 参重载
→ `polyMeshGeometry.C:2346` 转发到 `polyMeshGeometry.C:1989` 的 7 参实现。

> 全树中**只有** `polyMeshGeometry` 定义了 `checkCellDeterminant`，因此 `checkGeometry.C` 里 `mesh` 必为 `polyMeshGeometry`（或其子类），调用解析到 `polyMeshGeometry::checkCellDeterminant`。**故 checkMesh 的 cellDeterminant = `polyMeshGeometry` 的全面公式，而非 `primitiveMeshTools` 的内部-only 公式。**

---

## 2. 公式原文引用

### 2.1 `polyMeshGeometry::checkCellDeterminant`（checkMesh 实际所用）—— `polyMeshGeometry.C:2007-2036`

```cpp
2007      for (const label celli : affectedCells)
2008      {
2009          const cell& cFaces = cells[celli];
2010
2011          tensor areaSum(Zero);
2012          scalar magAreaSum = 0;
2013
2014          for (const label facei : cFaces)          // 单元的全部面（含边界）
2015          {
2016              scalar magArea = mag(faceAreas[facei]);
2017              magAreaSum += magArea;
2018              areaSum += faceAreas[facei]*(faceAreas[facei]/(magArea+VSMALL));
2019          }
2020
2021          scalar scaledDet = det(areaSum/(magAreaSum+VSMALL))/0.037037037037037;
2022
2023          minDet = min(minDet, scaledDet);
2024          sumDet += scaledDet;
2025          ++nSumDet;
2026
2027          if (scaledDet < warnDet)
2028          {
2029              ++nWarnDet;
...
```

逐条回答任务卡的问题：

① **归一化分母是什么？**
`magAreaSum = Σ |faceAreas[facei]|`，即该单元**全部面**面积向量模之和（`polyMeshGeometry.C:2017-2018`）。不是 `magSf` 单项、不是 `max(magSf)`、也不是单元体积。

② **`det(...)/0.037037...` 的完整上下文与量纲**
`areaSum = Σ_i S_i·(S_i/|S_i|)`。在 OpenFOAM 中 `vector * vector` 为并矢（dyadic）得 `tensor`，故
`areaSum = Σ_i |S_i|·(û_i û_iᵀ)`（û_i = S_i/|S_i| 为单位法向）。
`scaledDet = det( areaSum / (Σ|S_i|) ) / 0.037037037037037`。
其中 `1/0.037037037037037 = 27 = 3³`，作用是把立方体归一到 1（立方体时 `areaSum/(Σ|S|) = I/3`，`det=1/27`，`×27=1`）。**无量纲**（面积矢量模相消，纯方向并矢的行列式）。

③ **额外 min 项 / 符号处理 / 面积矢量朝向**
- 朝向约定：无符号处理。`S_i·(S_i/|S_i|) = |S_i|·(±û_i)(±û_i)ᵀ = |S_i|·û_i û_iᵀ`，符号在并矢中自相消。即 **owner/neighbour 朝向、面节点顺序都不影响结果**（这也解释了本地脚本 `orient='raw'/'cons'` 两分支为何结果一样——该分支是冗余的）。
- `VSMALL` 防除零（`polyMeshGeometry.C:2018,2021`）。
- 无显式 `min`/截断项；仅当某面 `|S_i|→0` 时该项被 `VSMALL` 抑制。

④ **checkMesh 实际调用的是哪个重载/路径**
`checkGeometry.C:865` 的 `mesh.checkCellDeterminant(true, &cells)` → 2 参重载 `polyMeshGeometry.C:2337` → 7 参 `polyMeshGeometry.C:1989`。`faceAreas` 为几何面面积矢量 `Sf`（polyMeshGeometry 缓存的 `faceAreas_`），`warnDet` 缺省阈值 0.001（日志 `Cells with small determinant (< 0.001)` 与之吻合）。

### 2.2 `primitiveMeshTools::cellDeterminant`（库函数，本次 checkMesh 未走此路）—— `primitiveMeshTools.C:490-553`

原文关键行：

```cpp
494              // Calculate local normalization factor
495              scalar avgArea = 0;
497              label nInternalFaces = 0;
499              forAll(curFaces, i)
500              {
501                  if (internalOrCoupledFace.test(curFaces[i]))
502                  {
503                      avgArea += mag(faceAreas[curFaces[i]]);
504                      nInternalFaces++;
505                  }
506              }
509              if (nInternalFaces == 0 || avgArea < ROOTVSMALL)
510              {
511                  cellDeterminant[celli] = 0;
512              }
513              else
514              {
515                  avgArea /= nInternalFaces;        // mean over INTERNAL faces only
517                  symmTensor areaTensor(Zero);
519                  forAll(curFaces, i)
520                  {
521                      if (internalOrCoupledFace.test(curFaces[i]))
522                      {
523                          areaTensor += sqr(faceAreas[curFaces[i]]/avgArea);
524                      }
525                  }
...
553                  cellDeterminant[celli] = mag(det(areaTensor))/8.0;
```

要点（与 2.1 的**差异**才是关键）：
- 只累加**内部/耦合面**（`internalOrCoupledFace.test`，`primitiveMeshTools.C:501,521`）；边界面的贡献被完全排除。
- 归一化分母 `avgArea` = 内部面 `|S|` 的**均值**（`primitiveMeshTools.C:515`）。
- `areaTensor += sqr(S_i/avgArea)`，即 `(S_i/avgArea)(S_i/avgArea)ᵀ`，`sqr(v)=v vᵀ`。
- 末项 `/8.0`（`primitiveMeshTools.C:553`）；立方体特征值 2,2,2，`det=8`，`/8=1`。
- 若单元无内部面或 `avgArea<ROOTVSMALL` → 该单元 `=0`（`primitiveMeshTools.C:509-512`）。

> 注：两个公式都会把**立方体归一化到 1**，但加权与面集合不同，对退化四面体给出不同数值。任务卡里提到的「`0.125*mag(det(sumSST))` 之类项」对应的是 **`/8.0`**（0.125），即 `primitiveMeshTools` 路径；而 checkMesh 实际跑的是 `polyMeshGeometry` 路径（`/0.037037…` ≈ ×27）。

---

## 3. 本地重建脚本的差异根因

脚本 `outputs/T-001/scripts/reconstruct_determinant_from_polymesh.py` 的算法（`reconstruct...py:123-143`）：

```python
for orient in ('raw', 'cons'):
    for norm in ('mean', 'max'):
        ...
        mag = np.linalg.norm(sf, axis=1)                  # 全部面的 |S|
        scl = mag.mean() if norm=='mean' else mag.max()  # mean 或 max，覆盖全部面
        ahat = sf / scl
        tens = np.einsum('ki,kj->ij', ahat, ahat)        # Σ (S_i/scl)(S_i/scl)ᵀ
        dets[ci] = np.abs(np.linalg.det(tens)) / 8.0
```

与 `polyMeshGeometry` 公式（§2.1，checkMesh 实际所用）的差异：

| 维度 | 标准 `polyMeshGeometry` 公式 | 本地脚本 | 是否一致 |
|---|---|---|---|
| 面集合 | 单元**全部面** | 单元全部面 | ✅ |
| 面权重 | `\|S_i\|`（线性） | `\|S_i\|²/scl²`（平方） | ❌ |
| 归一化 | `/ (Σ\|S_i\|)` | `/ scl²`（scl=mean 或 max） | ❌ |
| 末项 | `/0.037037…`（×27） | `/8.0` | ❌ |
| 朝向 | 并矢自消，无关 | 也无关（冗余分支） | ✅（无关） |

与 `primitiveMeshTools` 公式（§2.2）的差异：

| 维度 | `primitiveMeshTools` | 本地脚本 | 是否一致 |
|---|---|---|---|
| 面集合 | **仅内部面** | 全部面 | ❌ |
| 归一化 | 内部面 `\|S\|` 的均值 | 全部面 mean/max | ❌ |
| 末项 | `/8.0` | `/8.0` | ✅ |

**根因定位**：
- 脚本用了 **`|S|²` 加权而非 `|S|` 加权**，且归一化用单个标量 `scl`（mean/max）而非 `Σ|S_i|`，末项常数错用 `/8` 而非 `/0.037037`。
- 若对齐 `primitiveMeshTools`，还错在**把边界也算进去了**（内部面-only 才是该公式）。
- `orient` 分支（raw/cons）确为冗余：并矢 `ûûᵀ` 与面积矢量符号无关，无论是否翻转，结果一致。这也说明脚本“两种朝向都试过”并不能逼近 checkMesh。

因此脚本产出的 `mean: 7.40e-08/575`、`max: 1.16e-09/13441` **既不等于 `polyMeshGeometry` 公式、也不等于 `primitiveMeshTools` 公式**，自然对不上日志的 `1.11163982652e-07 / 585`。这些数字是“写错的算法”的产物，不具有判据价值。

---

## 4. 判决：本地复算「不可作判据」，以 checkMesh 为准

**选「修不好」分支。** 证据：

(a) **参考二进制是定制构建，精确公式不可从源码 100% 确认。**
日志打印文本 `(wellposedness)`、`minimum: X average: Y`、`***Cells with small determinant (< 0.001) found, number of cells: N` 在整棵 v1912.200626 源码树中搜索无果；源码中 `polyMeshGeometry::checkCellDeterminant` 打印的是 `"Cell determinant (1 = uniform cube) : average = ...  min = ..."`（`polyMeshGeometry.C:2047`）。即便把脚本“修正”成对齐某个标准公式，也无法保证对齐日志那个定制构建——**缺的是“那个构建的源码”，不是“本地脚本的算法”**。

(b) **foam_repaired 的 polyMesh 不在本机（仅在 WSL），零-CPU 车道无法取数。**
已确认本机 `D:\项目\鼻腔建模` 与 `C:\ts_work` 下没有 `foam_repaired/constant/polyMesh`（仅有其他无关算例的 polyMesh）。没有真实 `points/faces/owner/neighbour`，无法跑任何修正后的脚本做实证对照。

(c) **现有脚本公式本身写错（§3）。**
其 `7.40e-08/575`、`1.16e-09/13441` 不是对任一标准公式的忠实复现，不可作为判据。

→ **结论**：在 T-001-A 的约束（只读源码、零-CPU、本机无 foam_repaired 网格）下，本地复算既不能证明其正确、也无法补齐与定制构建之间的信息差；**该指标不可作本地判据，一切以 `checkMesh -allGeometry -allTopology` 的 stdout 为准**（即 `min = 1.11163982652e-07`、`585` 个单元 `<0.001`）。

> 备注：若日后要在本机独立复算，唯一可靠做法是**直接调用该定制 checkMesh 二进制对同一 polyMesh 重跑**（或在获得该构建源码后，按 `polyMeshGeometry.C:1989` 的全-面 `|S|` 加权公式、末项 `/0.037037…` 重新实现，并用 foam_repaired 的 polyMesh 实证）。当前车道不具备这两样输入。

---

## 5. `Failed 2 mesh checks` 的两项（日志 + 源码双侧确认）

`checkMesh.log`（Oct 13 22:54:28）中带 `***` 失败标记且对应 `noFailedChecks++` 的两项：

1. **Cell determinant (wellposedness)** —— `***Cells with small determinant (< 0.001) found, number of cells: 585`
   （log 第 102 行；源码计数 `checkGeometry.C:865` 调用 → `:867 noFailedChecks++;`）

2. **Face interpolation weight (< 0.05)** —— `***Faces with small interpolation weight (< 0.05) found, number of faces: 114`
   （log 第 106 行；源码 `checkGeometry.C:905` `mesh.checkFaceWeight(true, 0.05, &faces)` → `:907 noFailedChecks++;`）

其余拓扑检查（Boundary definition OK、Cell to face addressing OK …）与几何检查（openness、aspect ratio、face area、volume、non-ortho、skewness、face tets、edge length、angles、flatness、concave、face volume ratio）**全部 OK**，故恰好为 **2** 项失败。最终 `Failed 2 mesh checks.`（`checkGeometry.C:1154 return noFailedChecks;`）。

> 注意：112818 个 undefined faces（来自 `gmshToFoam`）**不计入这两项失败**，属于边界三角形提示（`Boundary definition OK` 已确认 4 patch 面数合计 112818、无 defaultFaces）——那是 T-001 的 R6 议题，与本判据无关。

---

## 6. 证据出处索引

| 结论 | 出处 |
|---|---|
| `cellDeterminant` 位置（库函数） | `primitiveMeshTools.C:456-559` |
| checkMesh 实际走向（全面公式） | `polyMeshGeometry.C:1989-2036`、`2337-2356` |
| checkMesh 调用点 | `checkGeometry.C:865` |
| 面权重 `\|S_i\|`、分母 `Σ\|S_i\|`、末项 `/0.037037…` | `polyMeshGeometry.C:2014-2022` |
| `primitiveMeshTools` 内部-only + mean + `/8` | `primitiveMeshTools.C:499-553` |
| 打印文本差异（定制构建佐证） | 全树搜索 `"wellposedness"` / `"small determinant"` / `"minimum:"` 无命中；源 `polyMeshGeometry.C:2047` 文本不同 |
| 两项失败计数 | `checkGeometry.C:867`（cell det）、`:907`（face weight）、`:1154` |
| 日志原始数值 | `outputs/T-001/logs/checkMesh.log:101-111` |

---

*审计完成。未修改任何源码、未触碰 `work/**`、未跑 WSL 重活。*
