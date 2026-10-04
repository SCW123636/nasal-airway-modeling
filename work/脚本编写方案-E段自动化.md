# 脚本编写方案：E 段自动化（体网格 → 求解 → 指标提取）

> 版本：2026-10-02 v1 ｜ 交付对象：外部执行 AI ｜ 适用范围：第一批 S1–S4（可自证闭环）
> 本文档只描述**要写什么、怎么验**。不包含实现代码。执行方不得借本文档推断任何患者结果。
> 上层目的：把 `work/07_cfd_pipeline` 里目前只能跑合成矩形通道的 OpenFOAM 链路，扩展成能**吃真实表面**并**回读可信指标**的可重放管线——这是「患者 CFD 结果 = 0」的直接堵点。

---

## 0. 执行前必读（先读这 5 个文件，不要凭本文档猜）

| 文件 | 为什么必须读 |
|---|---|
| `work/07_cfd_pipeline/solver_reference/run_reference.py` | **S2 的唯一模板**。已验证可跑通：自动写 case → blockMesh → checkMesh → simpleFoam → foamToVTK。直接复用其 `execute()` 与环境封装 |
| `work/lib/cfd_contract.py` | 结果契约与门禁。患者结果被硬性拦在 `review.status=confirmed and review.method=human` 之后 |
| `work/07_cfd_pipeline/solver_install/求解环境与待接入项.md` | OpenFOAM 版本、环境变量、命令可用性、已知坑 |
| `work/07_cfd_pipeline/当前进度与使用说明.md` | 当前真实状态与「不能误报」清单 |
| `work/04_cfd_ready/验证矩阵.md` | 边界条件与逐格必记指标口径 |

---

## 1. 环境硬约束（实测，违反必失败）

### 1.1 两套 Python，不要混

| 用途 | 解释器 |
|---|---|
| Windows 侧脚本 | `C:\Users\lenovo\.workbuddy\binaries\python\envs\nasal-cfd\Scripts\python.exe` |
| WSL 侧脚本 | WSL Ubuntu-22.04 内的 python3（**不能**用 Windows 那个直接跑 OpenFOAM） |

### 1.2 OpenFOAM 调用方式（封装错了必失败）

版本 `1912.200626-1`。**直接 source `/usr/share/openfoam/etc/bashrc` 会失败**——该包引用了缺失的辅助脚本。必须显式给三个变量：

```
WM_PROJECT_DIR=/usr/share/openfoam FOAM_ETC=/usr/share/openfoam/etc WM_PROJECT_VERSION=v1912
```

从 Windows 侧调用的等价形式（见 `求解环境与待接入项.md` L36）：
```
wsl.exe -d Ubuntu-22.04 -- env WM_PROJECT_DIR=/usr/share/openfoam FOAM_ETC=/usr/share/openfoam/etc WM_PROJECT_VERSION=v1912 <command>
```

⚠️ **已知限制**：`wsl.exe` 在某些沙箱配置下被拦截。**因此每个 WSL 侧脚本都必须设计成「用户可手动执行」**，并在 Windows 侧提供 `--dry-run`（只生成 case 文件、不调求解器），使得即使 WSL 不通也能验证 S1 的正确性。

### 1.3 v1912 的词典口径（不要套新版）

- 用 `constant/transportProperties`（`transportModel Newtonian; nu ...;`）+ `constant/turbulenceProperties`（`simulationType laminar;`）
- **不要**用 `foamRun` / `incompressibleFluid` / `momentumTransport`（那是另一发行系列）
- 官方示例在 `/usr/share/doc/openfoam-examples/examples/`
- 离散格式建议沿用 `incompressible/simpleFoam/pitzDaily/system/fvSchemes`（其 SHA-256 已写入参考 manifest，可追溯）

### 1.4 单位与量纲（三个真实坑）

| 坑 | 正解 |
|---|---|
| STL 是 mm，OpenFOAM 是 m | `convertToMeters 0.001;` 或几何先除 1000。**不转换会得到 1000 倍错误的 Re 与压降** |
| simpleFoam 的 `p` 是**运动学压力** | 单位 `m²/s²`，维度 `[0 2 -2 0 0 0 0]`；**乘 ρ 才是 Pa**（ρ=1.2 kg/m³） |
| nu 用运动黏度 | `nu = MU/RHO = 1.81e-5 / 1.2 = 1.5083e-5 m²/s` |

### 1.5 其他

- **中文路径**：Windows 侧中间产物一律走 `C:\ts_work`（规避 ITK/NIfTI 中文写盘失败）。结果可回写中文目录，中间计算不行。
- **PHI 红线**：患者数据只能用 `资料/脱敏数据_clean/`（B′）。原始 `资料/脱敏数据/患者ct+鼻空腔建模/` 含患者与医生真名、医院实名地址，**禁止读取、复制、外发**。第一批 S1–S4 **完全不需要碰患者数据**。
- **测试基线**：`python -m unittest discover -s work/lib -p "test_*.py"` 当前 **122 passed**。新增脚本**不得**让这个数下降；新脚本自带测试放在 `work/lib/test_<name>.py`。

---

## 2. 脚本清单与依赖顺序

```
S1 surface_to_case.py      (Windows)  真实表面 -> OpenFOAM case 骨架
S2 run_openfoam_case.py    (WSL)      通用求解执行器（泛化 run_reference）
S3 extract_cfd_metrics.py  (双端)     结果 -> 指标 JSON
S4 phantom_validation.py   (驱动)     圆管 phantom 端到端对账 -> pass/fail
```

依赖：`S4 → S3 → S2 → S1`。**必须按 S1→S2→S3→S4 顺序实现**，每完成一个先自验再进下一个。

第二批（本文档只给接口，不在第一批实现）：S5 `review_record.py`、S6 `surface_prep.py`。见 §8。

---

## 3. S1 `work/lib/surface_to_case.py`

### 3.1 目标
把一份**带命名 solid 分区的表面文件**（.stl 或 .vtp）转成一份**字段完整、可直接被 S2 执行的 OpenFOAM case 目录**，并产出可追溯的 `case_manifest.json`。

### 3.2 输入
```
--surface <path>        表面文件（.stl 或 .vtp）
--patch-map <json>      {"nostril_L":"inlet", "nostril_R":"inlet",
                         "nasopharynx":"outlet", "wall":"wall"}
--out <dir>             输出 case 目录（必须不存在，防覆盖）
--cell-size <mm>        背景网格目标尺寸（默认 0.4）
--refine-level "n n"    castellated 细化级别（默认 "1 1"）
--location-in-mesh "x y z"   域内一点（毫米），snappyHexMesh 必需
--solver laminar|kOmegaSST
--dry-run               只写文件，不返回执行命令
```

### 3.3 输出
```
<out>/0/p  <out>/0/U   （+ k, omega, nut 若 SST）
<out>/constant/triSurface/<name>.stl
<out>/constant/transportProperties
<out>/constant/turbulenceProperties
<out>/system/controlDict
<out>/system/fvSchemes         （复制自 pitzDaily，勿手写格式名）
<out>/system/fvSolution
<out>/system/blockMeshDict     （背景盒，包围盒外扩 ≥ 2×cell-size）
<out>/system/snappyHexMeshDict
<out>/case_manifest.json
```

`case_manifest.json` 至少含：表面文件 **SHA-256**、单位（`mm`，已转换标记）、`convertToMeters`、patch 映射原样、包围盒、cell_size、细化级别、locationInMesh、solver、`fvSchemes` 来源与 SHA-256、生成时间戳、脚本版本。
> 教训来源：既有 `nose.stl`（80 字节头全 0x00）**不含任何生成参数**，无法追溯，因此不可当金标准。本脚本产出的每个 case 都必须自带完整生成参数。

### 3.4 实现步骤
1. 读表面，提取各 solid / region 名；与 `--patch-map` 求交，**未映射的分区直接报错退出**（不许静默丢弃）。
2. 计算包围盒，`convertToMeters 0.001` 处理 mm→m；外扩生成背景 blockMesh。
3. 写 `snappyHexMeshDict`：geometry 指向 triSurface、`castellatedMesh true`、`snap true`、refinementSurfaces 按 patch 名分级、`locationInMesh` 用转换后的点。
4. 写 `0/` 字段：p（`[0 2 -2 0 0 0 0]`，uniform 0）、U（inlet 用 `flowRateInletVelocity` 或 `fixedValue`，按 §6.1 主边界；wall `noSlip`；outlet `fixedValue uniform 0` 表压）。
5. `fvSchemes` **复制** pitzDaily 的，**不要**自己写格式名（v1912 格式名与新版不同，手写极易失败）。
6. 写 `case_manifest.json`，并对所有写出文件算 SHA-256 登记。

### 3.5 验收（可跑）
```bash
python work/lib/surface_to_case.py --surface <phantom.stl> --patch-map <map.json> \
  --out C:\ts_work\case_test --location-in-mesh "0 0 0" --dry-run
```
通过判据（**全部满足**）：
- [ ] 退出码 0，`<out>` 下 10 个文件全部存在
- [ ] 用文本打开 `blockMeshDict` 可见 `convertToMeters 0.001`
- [ ] `snappyHexMeshDict` 里每个 patch 名都能在 `--patch-map` 找到
- [ ] `case_manifest.json` 的 SHA-256 与重算一致
- [ ] 故意传一个含未映射 solid 的 STL → **必须非 0 退出并报错**
- [ ] 对同一输入跑两次，`case_manifest.json` 除时间戳外逐字节一致（确定性）
- [ ] 新增 `work/lib/test_surface_to_case.py`，上述至少 4 条固化为 unittest

---

## 4. S2 `work/07_cfd_pipeline/solver/run_openfoam_case.py`（WSL 侧）

### 4.1 目标
把 `run_reference.py` 里**只认合成矩形通道**的执行逻辑，泛化成**吃任意 case 目录**的通用执行器，逐步执行并留痕。

### 4.2 硬性要求
- **复用** `run_reference.py` 的 `execute()` 与环境封装，**不要重写**。
- 必须用 WSL 内 python3 运行（脚本 docstring 要写明，和 `run_reference.py` 一样）。
- 每一步单独记 `{command, exit_code, elapsed_seconds, log_path}`，**任一步非 0 立即抛出并保留已有日志**（不得删日志后重试）。

### 4.3 输入 / 输出
```
--case <dir>          S1 产出的 case 目录
--steps blockMesh,snappyHexMesh,checkMesh,simpleFoam,foamToVTK   （可按序子集）
--env-check           只验证环境变量与命令版本，不建 case
```
输出：`<case>/run_manifest.json`（步骤记录 + 退出码 + 日志路径 + 开始/结束时间 + OpenFOAM 版本），以及各步 `log.*`。

### 4.4 实现步骤
1. 参数解析；`--env-check` 时打印 `blockMesh -help` 等退出码并退出。
2. 校验 case 目录必备文件齐全，缺一个就列出缺失清单再退出（**不许**带着残缺 case 去撞求解器）。
3. 组装环境字典（§1.2 三个变量 + 继承 `os.environ`）。
4. 按 `--steps` 顺序执行；`checkMesh` 用 `-allGeometry -allTopology`。
5. `foamToVTK` 用 `-latestTime -ascii -fields (p U)`（SST 时追加 `k omega`）。
6. 写 `run_manifest.json`；把 `case_manifest.json` 的内容**一并嵌入**（保证结果可追溯到输入几何）。

### 4.5 验收
先在已验证的合成 case 上回归（不得破坏既有结果）：
```bash
# 在 WSL 内
python3 run_openfoam_case.py --case .../poiseuille_v1912_verified/medium --steps checkMesh,simpleFoam,foamToVTK
```
通过判据：
- [ ] 全部步骤退出码 0，`run_manifest.json` 记录完整
- [ ] 对中网格重跑出的压降与既有 `0.215879249` 在 1e-6 内一致（可复现）
- [ ] 人为删掉一个必备文件 → 非 0 退出且列出缺失项
- [ ] 人为让 `simpleFoam` 失败（如改坏词典）→ 非 0 退出，**且前序日志仍在**

---

## 5. S3 `work/lib/extract_cfd_metrics.py`

### 5.1 目标
从 `foamToVTK` 的 VTK 输出 + `log.simpleFoam` + `run_manifest.json`，提取**验证矩阵要求的指标**，写成结构化 JSON。

### 5.2 必须计算的指标（无歧义，缺输入即报错）

| 指标 | 算法 | 来源 |
|---|---|---|
| `delta_p_pa` | 入口面积平均静压 − 出口面积平均静压，**乘 ρ=1.2** | VTK p 场（运动学） |
| `total_flow_m3s` | 入口面法向流量绝对值之和 | VTK U 场 |
| `split_ratio` | Q_L / (Q_L+Q_R)，按左右入口 patch 分 | VTK U 场 |
| `max_velocity_mps` | 全域速度模最大值 | VTK U 场 |
| `nasal_valve_peak_mps` | 鼻阀截面峰值速度（截面由 `--valve-slice` 给定，缺失则 `not_computed`） | VTK |
| `wall_shear_force_n` | 壁面 patch 上 WSS 的面积分 | 需 `postProcess wallShearStress`；见 5.4 |
| `resistance_R` | Δp / Q（单位 Pa·s/m³，**报告时同时给 Pa·s/mL**） | 计算 |
| `symmetry_phi` | Q_L / Q_R | 计算 |
| `converged` | `log.simpleFoam` 含 `SIMPLE solution converged` | 日志 |
| `mass_imbalance_frac` | \|Q_in−Q_out\| / Q_in | VTK |

### 5.3 诚实性设计（**不许猜**）

以下指标**需要解剖分区定义**（下鼻道 / 中鼻道 / 嗅区），而我们**目前没有可靠分区标签**：
```json
"region_flow_fraction": {"status": "not_computed",
  "reason": "requires verified anatomic region labels; not available"}
```
- 支持 `--region-mask <nii>` 可选输入；给了才算，算不出就写 `not_computed`。
- **禁止**用「z 轴切片百分比」或「最大连通域」之类的代理去冒充解剖分区（三例交叉验证已证伪纯几何判据，见 MEMORY §四）。
- 层流工况的湍流强度字段必须写 `"report_status": "not_applicable"`，**不得填 0% 冒充**（契约已有此约束）。

### 5.4 WSS 的取法
v1912 需先跑 `postProcess -func wallShearStress` 生成场，再由本脚本读取。若该场不存在 → `not_computed`，**不得**用速度梯度手工拼一个替代值。

### 5.5 验收
- [ ] 在已验证 Poiseuille case 上：`delta_p_pa` 与既有 `0.215879249 Pa` 差 < 1%；`mass_imbalance_frac` < 1e-6
- [ ] 传入不存在的 VTK → 非 0 退出，不产出半份 JSON
- [ ] 不给 `--region-mask` 时 `region_flow_fraction.status == "not_computed"`
- [ ] 层流 case 的湍流字段为 `not_applicable`
- [ ] 新增 `work/lib/test_extract_cfd_metrics.py`

---

## 6. 边界条件口径（S1/S2 共用，以验证矩阵为准）

### 6.1 主工况（默认）
- 入口：两鼻孔**共用可调静压**；鼻咽出口 **0 Pa 表压**；外层反馈调入口静压使**总流量 = 15 L/min = 2.5e-4 m³/s**。
- 左右分流**由几何求**，**不得**预设 50/50，更不得把等分结果报成患者真实分流。
- ⚠️ `common_inlet_pressure_feedback` 适配器当前 **not_implemented**。第一批**只需能把「共静压入口 + 0 Pa 出口」的 case 建出来**，外层反馈循环留空并显式标注 `status: not_implemented`。
- 等分 7.5/7.5 L/min 只能作为**人为对照工况**，命名必须含 `equal_split_baseline`。

### 6.2 量级哨兵（新增，来自文献 PMC8062271）
文献实测 ENS 单侧鼻阻力 0.102 Pa·s/mL → 双侧并联 ≈ 0.051 → 15 L/min 对应 **Δp ≈ 12.8 Pa**。
- S3 应计算 `resistance_R` 并与该量级对照，输出 `magnitude_check: "within_literature_band" | "outside"`.
- ⚠️ 文献队列是 ENS（阻力偏低），哨兵区间 10–20 Pa **只用于发现几何/边界有病，不是合格线**，报告中必须带此警告。

### 6.3 其他工况
5 / 30 L/min 敏感性、k-ω SST（湍流强度 1% 与 5%）、Δp=18 Pa 压力驱动、录屏原样边界——均为**独立工况，不与主工况混表**。

---

## 7. S4 `work/lib/phantom_validation.py`

### 7.1 目标
**不碰任何患者数据、不需要人工审核**，用已知解析解的圆管 phantom 端到端证明 S1→S2→S3 成立。这是第一批唯一能自证"真值"的环节。

### 7.2 做法
1. 程序生成一根直圆管 STL：`L=40 mm`、`D=4 mm`，三个命名 solid：`inlet` / `outlet` / `wall`。
2. 走 S1 建 case（cell_size 取 0.4 / 0.2 两档）→ S2 执行 → S3 提取。
3. 与 Hagen–Poiseuille 解析解对账：
   ```
   Δp = 128 μ L Q / (π D⁴)      μ = 1.81e-5 Pa·s
   ```
   取 Q = 15 L/min = 2.5e-4 m³/s。

### 7.3 通过判据（可证伪）
- [ ] 两档网格 Δp 相对解析解误差 **< 5%（粗）/ < 2%（细）**，且**误差随细化单调下降**
- [ ] `mass_imbalance_frac` < 1e-6
- [ ] `converged == true`（日志含 `SIMPLE solution converged`）
- [ ] 峰值速度与解析 `2·U_mean` 差 < 5%
- [ ] 输出的 `validation.json` 内含：STL SHA-256、网格尺寸、解析值、数值值、相对误差、判定 pass/fail

### 7.4 失败时的处置
**不许调宽容差让它过**。判定 fail 就写 fail，把数值与日志一并保留，交回人工排查。

---

## 8. 第二批接口（不在第一批实现，仅预留）

| 脚本 | 职责 | 依赖 |
|---|---|---|
| `S5 review_record.py` | 生成/校验人工审核记录 `review.json`。契约要求 7 项：`reviewer`、`reviewed_at`、`record_file`、`reviewed_geometry_sha256`、`confirmed_boundaries`（须含双鼻孔+鼻咽）、`oral_exclusion_confirmed`、`sinus_boundary_policy_confirmed`。**只记录人工输入，绝不自动确认** | `cfd_contract.py` |
| `S6 surface_prep.py` | 标签体 → watertight 表面 + 开口 patch 标记。⚠️ **鼻孔入口与鼻咽出口必须保持开放**，禁止全局封洞（这是 Blender 人工流程最容易做错的一步）；修复用 `vtkFillHolesFilter`+`vtkCleanPolyData`+`vtkPolyDataNormals`；输出 STL **必须带命名 solid** 以配合 S1 | 需先装 vtk（当前 venv 无，`geo_manifest.py` 因此退化为 .mha 占位） |

---

## 9. 红线（违反即不合格）

1. **不得产出任何患者 CFD 结果**。`cfd_contract` 门禁要求 `review.status=confirmed and review.method=human`；第一批一律用 phantom 或非患者几何。
2. **不得读取原始 B 块患者数据**（`资料/脱敏数据/患者ct+鼻空腔建模/`）。只允许 `资料/脱敏数据_clean/`（B′），第一批实际不需要。
3. **不得用参考/解析数据填充患者图层**，不得把圆管结果标成鼻腔结果。
4. **不得把 `not_computed` 写成 0 或占位数值**；不得把层流的湍流强度填 0%。
5. **不得**为了让测试通过而放宽容差、删除日志后重跑、或把失败记作收敛。
6. **不得**让 `python -m unittest discover -s work/lib -p "test_*.py"` 的通过数从 122 下降。
7. **不得**在 Windows 中间产物路径里使用中文（一律 `C:\ts_work`）。
8. 每个脚本产出的文件都必须带**生成参数 + 输入 SHA-256**，不留无法追溯的产物。

---

## 10. 交付与汇报格式

每完成一个脚本，交付方需给出：
1. 脚本路径 + 行数量级
2. **实际执行的验收命令与原始输出**（不是复述结论）
3. 通过判据逐条勾选结果，未通过的照实写
4. 新增/修改文件清单
5. 明确标注：`已实现` / `未实现` / `已验证` / `未验证`——四者不许混用
