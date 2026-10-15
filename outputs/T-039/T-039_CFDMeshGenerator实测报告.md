# T-039 · SlicerVMTK `CFD Mesh Generator` 实测（chali-edited.stl）

- 执行：2026-10-15 22:26 – 23:50（段主对话亲自执行）
- 触发：T-038 判定「体网格段值得实测」→ 用户 `annituijiande`（按推荐装扩展 + 跑最小试验）→ 用户投喂 `chali-edited.stl` 并说「尝试跑这个的结果出来」
- 环境写域：`软件/slicer/.../Extensions-34645/`（SlicerVMTK 23190ba + ExtraMarkups 054b1d3，17 MB；gitignored，删目录即还原）+ Slicer 自带 Python 的 `netgen-mesher 6.2.2606` / `netgen-occt 7.8.1`
- 声明：**全程无患者数据**；不改共享代码；不动 18 Pa / 阈值口径；未 `git commit`

---

## 0. 一句话结论

**这条链能跑通，而且产出的 OpenFOAM 网格拓扑上完全干净（单区域、水密、体积逐位守恒）。但在这份 STL 上：默认参数两处必失败（表面重网格把封闭面搞坏；边界层自折叠），只有「关重网格 + 关边界层」能出网格；出网格过不了 `checkMesh` 的 5–6 项质量门，且质量劣于患者 b15 网格一个量级。** 三个病根彼此独立、都已定位。**Netgen 与 TetGen 在 det / 非正交上几乎等价，但 Netgen 在插值权（7.8×）与体积比（63×）上明显更差，且慢 13.5×。**

---

## 1. 输入几何体检（`chali-edited.stl`）

| 项 | 值 |
|---|---|
| 格式 | 二进制 STL，13,675,384 B = 84 + 50×273,506（**逐字节核对**） |
| 三角面 / 唯一点 | 273,506 / 136,649 |
| 包围盒 | `[-44.205, -51.207, -58.559]` → `[43.114, 46.975, 44.396]` |
| **单位** | **米**（×1000 → mm；跨度 87.3 × 98.2 × 103.0 mm） |
| 表面积 / 有向体积 | 383.85 cm² / **8.86280e-05 m³ = 88.63 cm³**（正 → 法向朝外） |
| 边界边 / 非流形边 / 退化面 | **0 / 0 / 0**（水密、干净） |
| 连通分量 | **1** |
| 法向一致性 | 有向边 820,518 = 2 × 无向边 410,259 → **一致** |
| 射线穿透 | 187 条命中射线**全部偶数次**；内外长度比 0.238；单射线内长中位 **16.35 mm** |
| **等效三角边长** | **≈ 0.569 mm**（均面 0.1403 mm²） |

**判定：实心封闭空气域**（非薄壁壳）。特征尺寸 4V/A = 9.2 mm，与副鼻窦/鼻腔气道量级相符。
**关键缺陷：表面上没有任何开口** —— 全封闭，所以最终网格只有 1 个 patch。

> 语义提示：文件名 `chali` 我无法确定指代（人名/编号/物件皆可能）。上面全部判定是**从几何量出来的**，不依赖这个名字。若它指某个特定版本（例如已切好开口的），说一声我重跑。

---

## 2. 六格运行

统一入口（Slicer 5.12.4 headless）：
```powershell
$env:T039_JOB = "<job.json>"
& "D:\...\3D Slicer 5.12.4\Slicer.exe" --no-splash --no-main-window --testing `
  --python-script "D:\项目\鼻腔建模\outputs\T-039\run_mesher_generic.py"
```

| 格 | 引擎 | 表面重网格 | 边界层 | 体积尺寸 | 结果 | 耗时 |
|---|---|---|---|---|---|---|
| A | TetGen | 1.0 mm | 有（2 层 × 0.25） | 1.0 mm | ⛔ **边界层自折叠**（53 单元内翻，untangle 15 轮无改善） | 338.9 s |
| B | TetGen | 1.0 mm | 无 | 1.0 mm | ⛔ **重网格把面搞成非流形**（1 条边被 >2 面共享） | 137.5 s |
| C | TetGen | 0.7 mm | 无 | 0.7 mm | ⛔ **重网格仍非流形**（5 条边） | 283.0 s |
| **D** | TetGen | **关** | 无 | 1.0 mm | ✅ 1,891,233 tet + 273,524 边界三角 | **36.4 s** |
| **E** | TetGen | **关** | 无 | 0.7 mm | ✅ 4,059,715 tet + 273,524 边界三角 | 67.8 s |
| **F** | **Netgen** | **关** | 无 | 1.0 mm | ✅ 2,006,679 tet + 273,506 边界三角 | **490.7 s** |

**两次失败的原文（模块自己的报错，未改写）**
- A：`The boundary layer folded over itself: 53 of its cells are inside out or squashed flat after the sweep …`
- B/C：`The surface to be filled is not closed: N of its edges are open or shared by more than two triangles … Remeshing is the usual cause when the target edge length is far from the size of the triangles the surface arrived with`

### 病根定位（三条，互相独立）

1. **表面重网格对这份曲面不鲁棒。** B 用 1.0 mm（粗化 1.76×）坏 1 条边；C 用 0.7 mm（粗化 1.23×）**反而坏 5 条**。→ **不是尺寸失配**，是 VMTK `vtkvmtkSurfaceRemeshing` 在这份高曲率/薄壁起伏曲面上本身会产非流形边。**结论：这份几何上重网格必须关掉。**
2. **边界层在壁面自折叠。** A 已经是 `boundaryLayerOnCaps=False`（层只长在壁上、不上端盖），仍然折叠 → 说明折叠点不在「端盖与壁的角」，而在**壁面上的凹陷/缝隙**（鼻甲/窦口那类结构）。需要更薄（BL 因子 ↓）或更少子层。
3. **体积尺寸 > 表面尺寸 ⇒ 贴壁 sliver。** D（1.0 mm 体积 / 0.569 mm 表面）的 `det<0.001` 高达 17,839；E 把体积降到 0.7 mm 后**相对占比从 0.94% 降到 0.58%**、最大长宽比 **2106.71 → 130.16**、`Failed` **6 → 5**。方向对，但没消除。

---

## 3. 三格产出网格的 `checkMesh -allGeometry -allTopology`（OpenFOAM v1912 / WSL native FS）

**三格共同通过（无保留）：**
- Boundary definition / Cell-to-face / Point usage / Face vertices / Topological zip-up / Face-face connectivity — 全 OK
- **Number of regions: 1 (OK)**
- 补丁拓扑 `wall`：**ok (closed singly connected)**
- Boundary openness ~1e-17 OK；Cell volumes OK；Face pyramids OK；All angles in faces OK；Face flatness OK；Concave cell check OK
- **Total volume = 8.86281e-05 m³**，与 STL 的 8.86280e-05 **一致 → 体积守恒**

| 指标 | D · TetGen 1.0 | E · TetGen 0.7 | F · **Netgen 1.0** | 患者 b15（MEMORY 记录） |
|---|---|---|---|---|
| cells | 1,891,233 | 4,059,715 | 2,006,679 | 1,161,194 |
| **Failed mesh checks** | 6 | **5** | 6 | 2 |
| det<0.001（绝对 / 占比） | 17,839 / 0.94% | 23,655 / **0.58%** | 18,089 / 0.90% | 585 / 0.05% |
| cell determinant 最小 / 平均 | 0 / 0.135 | 0 / 0.153 | 0 / 0.123 | — |
| >70° 非正交（绝对 / 占比） | 7,132 / 0.182% | 9,380 / **0.114%** | 7,199 / 0.173% | — |
| 最大非正交 | 89.91° | 89.32° | **89.99°** | 87.3° |
| 低插值权 (<0.05) | 641 | **581** | **5,030** | 114 |
| 低体积比 (<0.01) | 6 | **5** | **380** | — |
| 最大长宽比 | 2,106.71 | **130.16（OK）** | **24,325.4** | — |
| 最大 skewness | 4.8826 | 4.8826 | 4.8826 | — |
| `upperTriangular` 面 | 1,044,285 | 有 | 有 | — |

**读法**

- **三格的 `det<0.001` 占比（0.6–0.9%）都比患者 b15（0.05%）高一个量级**，最大非正交也更高（89.3–90.0° vs 87.3°）。即在**「关重网格 + 关边界层」这一最不利配置**下，这套链产出的网格**质量确实不如项目现用的患者网格**。
- **引擎对比（同配置 D vs F，唯一变量 = 引擎）**：`det<0.001`（17,839 vs 18,089）与严重非正交（7,132 vs 7,199）**几乎等价**；但 **Netgen 在低插值权上差 7.8×、低体积比差 63×、最大长宽比差 11×**，且 **慢 13.5×**（490.7 s vs 36.4 s）。→ **许可上 Netgen 可用（LGPL），但默认设置下质量与速度都不如 TetGen。**（两侧都没调参，这是"默认 vs 默认"。）
- **尺寸效应（D vs E）**：体积尺寸贴近表面尺寸可把最大长宽比压到 OK 并减少失败项，但**不能消除 det<0.001** → 那些坏单元来自更根本的贴壁几何（表面 0.569 mm 的三角本身 vs 腔内结构），不是单靠调尺寸能解的。
- `upperTriangular`/`oneInternalFace`/`highAspectRatio` 等属记账/极少数单元问题，**如实列出，不豁免**。

---

## 4. VTU → OpenFOAM `polyMesh`（自研转换，`outputs/T-039/vtu_to_openfoam.py`）

面从四面体自身重建（每 tet 出 4 面，取向取自宿主单元 = 外法向），与边界三角形重合的面归边界面并取其 patch id；**内部面在前、边界面按 patch 在后**（OpenFOAM 约定）。

| 量 | D | E | F |
|---|---|---|---|
| 非正体积四面体 | 0 | 0 | 0 |
| 网格总体积 | 8.86281e-05 m³ | 8.86281e-05 m³ | 8.86281e-05 m³ |
| 边界三角未匹配 | 0 | 0 | 0 |
| 内部面键不匹配 | 0 | 0 | 0 |
| 面数（内部 + 边界） | 3,919,228 | 8,256,192 | 4,150,111 |
| patch | 仅 `wall` | 仅 `wall` | 仅 `wall` |

---

## 5. 单位与口径（易错处，显式记录）

- STL 是**米**，Slicer/VMTK 是 **mm** → 进 Slicer 前 ×1000，出 OpenFOAM 前 ×0.001（`--unit-scale`）。两侧都逐项核过（包围盒、体积三格一致）。
- 无 GUI 时走 `logic.processInThisProcess(paramNode)`（模块自己给脚本/测试标注的路径）。`processAndWait` 会 fork 一个 **不带我们在脚本里做的 sys.path / DLL 目录修复** 的 worker，故未采用——这是**我们对模块的用法偏离**，已记录。

---

## 6. 未验证 / 风险（诚实清单）

1. **边界层从未成功**（A 折叠）。T-038 的核心卖点「棱柱边界层」至今**未证实**。未试的更薄/更少子层配置还没跑。
2. **重网格在这份几何上不可用**（B/C 各坏一次）。这是**本次最重要的负面发现**，它同时否掉了「用重网格把表面调到目标尺寸」这条常规做法。
3. **没有入口/出口**：几何全封闭 → 网格只有 1 个 `wall` patch，**不能直接作为流动算例**。
4. **转换脚本 `vtu_to_openfoam.py` 是自研件**，未进 `work/lib/`、未过项目测试；`gmshToFoam` 这条替代路径未试。
5. 引擎对比是**默认设置 vs 默认设置**（TetGen 带 `q10` 质量约束；Netgen 带 `grading 0.3 / optimization 3`），没有调优，不能读成"引擎固有优劣"。
6. `Clip Vessel` 完全未碰（T-038 已记官方硬限制要求全分支有中心线）。
7. **原 T-039 卡里的解析圆管对照格未做**（同一条圆管跑这套链 → 与 T-036 干净管逐项比）。chali 是额外投喂的几何，不能替代那个对照。

## 7. 车道事故（如实记）

开跑前（22:25）`uptime` 确认 load 0.00。但**另一对话 23:14 起了 b15_maxh1 S-A 求解**（`simpleFoam` PID 1082，99.7% CPU，独占车道）。本卡 23:03–23:50 的 Slicer 网格 / numpy 转换 / checkMesh 与它**并行过**（各自单线程，冲击有限但真实存在）。
**教训：跨对话共享 CPU 车道必须每次重活前重新 `uptime`，不能只信本对话开场那一次。**

---

## 8. 下一步（按性价比排序，等裁定）

1. **边界层单独调参**：BL 因子 0.25 → 0.05 / 子层 2 → 1，在关重网格的前提下跑（这是唯一还没试的边界层方向，也是 T-038 卖点的关键）。
2. **解析圆管对照格**（原 T-039 卡验收项）：把 D 的配置搬到解析圆管上 → checkMesh 与 T-036 干净管逐项比，才能把「这份几何难」与「这套链不行」分开。
3. 若要当 CFD 用：**先给几何开入口/出口**（当前全封闭）。
4. 需要更细网格时，走 E 的路线（关重网格 + 体积尺寸贴表面），但要预期 det<0.001 不会消失。
5. 引擎选型：许可上 Netgen 可用，但默认参数下**建议先用 TetGen 做质量基线**；若必须 LGPL，再对 Netgen 调参（grading / optimizationSteps / volumeElementScaleFactor）。

## 9. 复现入口

```powershell
# ① 装扩展（headless；成功）
& "D:\项目\鼻腔建模\软件\slicer\3D Slicer 5.12.4\Slicer.exe" --no-splash --no-main-window --testing `
  --python-script "D:\项目\鼻腔建模\outputs\T-039\install_slicervmtk.py"

# ② 装 netgen 引擎（LGPL）——PyPI 直链极慢，清华镜像对该 wheel 403，故手工下 wheel 再本地装
& "...\bin\PythonSlicer.exe" -m pip install --no-input --no-deps `
  "D:\项目\鼻腔建模\outputs\T-039\wheels\netgen_mesher-6.2.2606-cp312-cp312-win_amd64.whl" `
  "D:\项目\鼻腔建模\outputs\T-039\wheels\netgen_occt-7.8.1-py3-none-win_amd64.whl"

# ③ 出网格（job 见 outputs/T-039/chali_job_*.json）
$env:T039_JOB="D:\项目\鼻腔建模\outputs\T-039\chali_job_norem.json"
& "...\Slicer.exe" --no-splash --no-main-window --testing `
  --python-script "D:\项目\鼻腔建模\outputs\T-039\run_mesher_generic.py"

# ④ 转 OpenFOAM + 门禁
& "C:\Users\lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe" vtu_to_openfoam.py `
  chali_norem/volume_mesh.vtu chali_norem/openfoam_case --unit-scale 0.001
wsl -d Ubuntu-22.04 -- bash -lc "cd /home/lenovo2/t039_chali && WM_PROJECT_DIR=/usr/share/openfoam \
  FOAM_ETC=/usr/share/openfoam/etc WM_PROJECT_VERSION=v1912 checkMesh -allGeometry -allTopology"
```

## 10. 环境还原

```powershell
# 卸扩展（下次启动 Slicer 前删掉即回到未装状态）
Remove-Item -Recurse -Force "D:\项目\鼻腔建模\软件\slicer\3D Slicer 5.12.4\slicer.org\Extensions-34645\SlicerVMTK"
Remove-Item -Recurse -Force "D:\项目\鼻腔建模\软件\slicer\3D Slicer 5.12.4\slicer.org\Extensions-34645\ExtraMarkups"
# 卸 netgen 引擎
& "D:\项目\鼻腔建模\软件\slicer\3D Slicer 5.12.4\bin\PythonSlicer.exe" -m pip uninstall -y netgen-mesher netgen-occt
```

## 11. 产物清单（`outputs/T-039/`）

| 路径 | 内容 |
|---|---|
| `T-039_CFDMeshGenerator实测报告.md` | 本报告 |
| `tube.stl` | 解析圆管 STL（sha256 `786c59f8…`，供圆管对照格复用） |
| `run_mesher_generic.py` | job 驱动的通用网格生成脚本（进 Slicer 跑） |
| `vtu_to_openfoam.py` | VTU → OpenFOAM polyMesh 转换（自研） |
| `install_slicervmtk.py` | headless 装扩展 |
| `chali_job_*.json` | 各格参数（norem / v07 / netgen / nobl / matched） |
| `chali_norem/{volume_mesh.vtu, openfoam_case/, log.checkMesh, mesher_run.json, convert_report.json}` | 格 D |
| `chali_v07/…` | 格 E |
| `chali_netgen/…` | 格 F（Netgen） |
| `chali/job 结果`、`chali_matched/`、`chali_nobl/` | 格 A / C / B 的失败记录（`mesher_run.json` 含原始报错） |
| `wheels/` | 两个 netgen wheel（离线可复用） |
| `nm.json`、`no.json` | PyPI 元数据（下载地址取证） |
