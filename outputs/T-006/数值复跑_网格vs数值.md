# T-006 ｜ 数值设置复跑：判别「网格致命」vs「数值不适用」

> **链路验证，不得报告为患者分流结论**
> `clinical_status: generalisation_test_only_no_human_review`

- 任务卡：`tasks/T-006.md`
- 执行：general-purpose-1（T-006 专项对话）**执行至 18:20 后被段主对话终止**；
  后续全部由**段主对话直接完成**（独立提取数据、人工终止求解、foamToVTK、本报告补写）。
  终止原因见 §9（该子代理四次报出不实信息，但其**落盘数据全部真实**，本报告 §1–§5 即其诚实产出）。
- 执行时间：2026-10-14 17:45 起，求解 17:53:53–18:38:22（**人工终止**，见 §6.2）
- case：`/home/lenovo2/patient_cfd/t004_diag/`（WSL native Linux FS）
- 求解器：OpenFOAM **v1912**（`Build: OPENFOAM=1912 patch=200626`）
- 硬件：24 vCPU / 7 GiB RAM，单核串行 `simpleFoam`，独占车道（开跑前 WSL `load average: 0.00, 0.00, 0.00`）

---

## 0. 一句话结论

**「网格致命」被推翻。** 同一张被 T-004 判为「致命」的网格（585 个 det<0.001 / 114 个低插值权面 / 最大非正交 87.3°），
在**只改数值设置**后：从「T=145 跳变、T=260 sigFPE 崩溃」变为**稳定迭代 533 步无任何崩溃**，
Δp = **10.29 Pa 落入 10–100 Pa plausibility 带**，质量不平衡相对 **7.2e-7**。
但**未完全收敛**（残差停在 p~1e-5 / U~1e-4 平台，residualControl 1e-6 不可达）→
网格 sliver 伤害的是「**可达精度**」而非「**稳定性**」——这是本次实验的新发现（见 §6.3）。

---

## 1. 现场核实（开工前，与任务卡逐项对齐）

| 核实项 | 命令 | 结果 |
|---|---|---|
| case 清场 | `ls -la /home/lenovo2/patient_cfd/t004_diag/` | ✅ 只剩 `0/`(U,p)、`constant/`、`system/`、`case_manifest.json` |
| `system/orig/` 备份 | `md5sum system/orig/*` | ✅ fvSolution `301403d1…`、fvSchemes `5ac7ce7e…`、controlDict `19f6903a…` —— 与任务卡完全一致 |
| 当前 system 是否已改 | `md5sum system/fvSolution system/fvSchemes system/controlDict` | ✅ 三份与 orig **逐位相同** → Run 1 修改**未写入**，从"写入修改"开始 |
| T-004 归档 | `ls -la /home/lenovo2/patient_cfd/t004_diag_T004_archive/` | ✅ `200/`、`VTK/`、`log.simpleFoam`、`log.checkMesh`、`log.foamToVTK`、`postProcessing/`、`run_manifest.json`、`run_status.json` 均在（只读参考） |
| simpleFoam 进程 | `pgrep -a simpleFoam` | ✅ 无 |
| 流体/湍流 | `cat constant/transportProperties constant/turbulenceProperties` | `nu = 1.508333333333e-05`、`simulationType laminar`（Run 1 不动） |
| 边界 | `cat 0/U 0/p` | 两鼻孔 `flowRateInletVelocity` 各 `1.25e-04 m³/s`（合计 15 L/min）、出口 `p fixedValue 0`、wall `noSlip`（不动） |

---

## 2. 改动清单（diff）

命令：`cd /home/lenovo2/patient_cfd/t004_diag && diff system/orig/X.orig system/X`

### 2.1 `system/fvSolution`

```diff
15c15
<  nNonOrthogonalCorrectors 0;
---
>  nNonOrthogonalCorrectors 2;
17c17,22
<  residualControl { p 1e-10; U 1e-8; }
---
>  residualControl { p 1e-6; U 1e-6; }
> }
> relaxationFactors
> {
>  equations { U 0.7; }
>  fields    { p 0.3; }
19d23
< relaxationFactors { equations { U 0.9; } }
```

| 项 | 旧值 | 新值 | 依据 |
|---|---|---|---|
| `nNonOrthogonalCorrectors` | 0 | 2 | 最大非正交 87.3°、>70° 面 204 个；惯例 2–3 |
| `residualControl` | `p 1e-10; U 1e-8;` | `p 1e-6; U 1e-6;` | 原值对稳态 SIMPLE 实际不可达，等于永不触发 |
| `relaxationFactors/equations/U` | 0.9 | 0.7 | 畸变网格惯例 |
| `relaxationFactors/fields/p` | **未设（默认 1.0 无松弛）** | 0.3 | SIMPLE 的 p 不加松弛极不稳定 |

### 2.2 `system/fvSchemes`

```diff
14a15
>  grad(U) cellLimited Gauss linear 1;
```

| 项 | 旧值 | 新值 |
|---|---|---|
| `gradSchemes/grad(U)` | 继承 `default Gauss linear`（无限幅） | `cellLimited Gauss linear 1` |
| `gradSchemes/default` | `Gauss linear` | **保留不动** |
| `snGradSchemes/default` | `corrected` | **保留不动** |
| `div(phi,U)` | `bounded Gauss linearUpwind grad(U)` | **保留不动**（其 `grad(U)` 引用已由上面的显式条目解析，未被破坏） |

### 2.3 `system/controlDict`

```diff
12c12
< endTime 500;
---
> endTime 1500;
```

- `writeInterval 200`、`purgeWrite 2`、`deltaT 1`、`startTime 0`、6 个 `surfaceFieldValue` functions —— **均不动**。

### 2.4 ⚠️ v1912 `relaxationFactors` 语法验证（"启动即验证"法）

WSL 内**无 OpenFOAM 源码树**（只有 `/usr/bin/simpleFoam`，`$FOAM_SRC` 为空），无法 grep 源码确认 `fields` 子字典是否受支持。

**处置**：先 `foamDictionary -entry endTime -set 2` 临时跑 2 步验证，**未沉默回退**。结果：

```
SIMPLE: convergence criteria
    field p	 tolerance 1e-06
    field U	 tolerance 1e-06
...
Time = 1
smoothSolver:  Solving for Ux, ...
GAMG:  Solving for p, Initial residual = 1, Final residual = 0.00906522345618, No Iterations 11
GAMG:  Solving for p, Initial residual = 0.0897279006237, ...   <- 非正交修正 #1
GAMG:  Solving for p, Initial residual = 0.0105868421352, ...   <- 非正交修正 #2
```

- ✅ **`fields { p 0.3; }` 写法被 v1912 接受**（无 `FOAM FATAL`、无 unrecognized keyword）→ **无需回退成扁平写法**。
- ✅ 每步 p 被解 **3 次**（1 主 + 2 非正交修正），证明 `nNonOrthogonalCorrectors 2` 真实生效。
- 验证后 `rm -rf 1 2 postProcessing log.syntaxcheck` 清场，`endTime` 复位 1500。

**最终 md5（case 内）**：
```
98de50a465e37683b005a0497e965a41  system/fvSolution
041be9d0e0f060f7d390fc3399e6eac5  system/fvSchemes
dffcd3326d17b8fe8c996465ef49c2e8  system/controlDict
```
（controlDict md5 与 Windows 侧原稿不同，仅因 `foamDictionary` 把 `endTime 1500;` 对齐为 `endTime         1500;`，语义相同；case 内最终版已复制到 `logs/system/`。）

---

## 3. 运行参数

```
cd /home/lenovo2/patient_cfd/t004_diag
source /usr/share/openfoam/etc/bashrc
simpleFoam > log.simpleFoam 2>&1
```

- `trapFpe: Floating point exception trapping enabled (FOAM_SIGFPE)`（与 T-004 同）
- 串行单进程（`nProcs : 1`）
- 起步速率：Time 1→9 用 45.72 s ≈ **5.1 s/step**（T-004 同段约 3.5 s/step；多出的开销来自每步 3 次 p 求解）

---

## 4. T-004 基线（从归档日志重算，供对照）

来源：`/home/lenovo2/patient_cfd/t004_diag_T004_archive/log.simpleFoam` 与 `.../postProcessing/*/0/surfaceFieldValue_0.dat`

### 4.1 ⚠️ 对任务卡一处事实的更正

任务卡/派活 prompt 称 T-004「前 ~250 步稳定」。**实测不成立**：

| Time | `sum local` 连续性误差 | 说明 |
|---|---|---|
| 1 | 0.111 | 起流 |
| 50 | 0.0703 | 稳定 |
| 100 | 0.0221 | 稳定（最优） |
| 125 | 0.0272 | 稳定 |
| **150** | **1.385** | **开始恶化（≈60× 于 T=100）** |
| 175 | 4.617 | 继续恶化 |
| 200 | 6.766 | 继续恶化 |
| 225 | 246.2 | 失稳 |
| 250 | 40612 | 崩溃前 |
| 259 | 6.25e19 | 指数爆炸 |
| 260 | — | `sigFPE` 崩于 `symGaussSeidelSmoother::smooth` |

鼻孔 L 面积加权平均 p（运动学，m²/s²）同步印证：T=140 时 7.139（稳）→ T=150 时 4.958 → T=170 时 4.070 → T=190 时 22.81 → T=200 时 34.70。

→ **T-004 真实恶化窗口：Time ≈ 145–150 起，Time ≈ 225 后指数爆炸，Time = 260 崩。**
→ 「稳定 250 步」应更正为「稳定约 145 步」。

### 4.2 T-004 稳定段基准量（Time = 100–140）

| 量 | 值 | 出处 |
|---|---|---|
| nostril_L 面积加权 p | 7.1509 m²/s² (T=100)、7.1387 (T=140) | `postProcessing/pressure_nostril_L/0/surfaceFieldValue_0.dat` |
| nostril_R 面积加权 p | 9.3223 m²/s² (T=100)、9.3274 (T=140) | 同上 |
| nasopharynx_outlet p | 0.0（固定） | 同上 |
| Δp_kin（L） | 7.151 m²/s² → **Δp ≈ 8.58 Pa**（ρ=1.2） | 计算 |
| Δp_kin（R） | 9.322 m²/s² → **Δp ≈ 11.19 Pa**（ρ=1.2） | 计算 |
| 鼻孔 L 面积 | 8.205263167455e-05 m² | dat 头 |
| 鼻孔 R 面积 | 8.115454417757e-05 m² | dat 头 |
| 出口 `sum(phi)` | 2.49965e-04 m³/s | `flow_nasopharynx_outlet/0/…dat` |
| 进出口质量不平衡 | (2.49965e-4 − 2.5e-4)/2.5e-4 = **0.014 %** | 计算 |

两鼻孔流量**等分**（各 1.25e-4 m³/s）但压力**不等**（7.15 vs 9.32），符合鼻腔左右不对称解剖。

---

## 5. Run 1 结果（进行中，增量回填）

> 状态：**运行中**。下列数据截至 **Time = 286**（ExecutionTime = 1417.1 s，即 ~4.95 s/step）。
> 未崩溃；`grep -c '^Time = '` 与末端日志实时核对。最终值待跑完后回填。

### 5.1 是否收敛（截至 Time = 286）

- **未出现 `FOAM FATAL` / `sigFPE` / 任何致命错误。**
- **已越过 T-004 的恶化起点（Time≈150）与崩溃点（Time=260）**，trajectory 全程平滑。
- 残差仍在单调下降，尚未触发 `residualControl`（p/U = 1e-6）。**跑到 endTime 1500 或提前触发 `SIMPLE solution converged`，二者之一，待定。**

### 5.2 residual 轨迹（`log.simpleFoam`，Ux/Uy/Uz/p 的 initial residual）

| Time | Ux | Uy | Uz | p |
|---|---|---|---|---|
| 1 | 1.000e+00 | 1.000e+00 | 1.000e+00 | 9.02e-02* |
| 2 | 3.473e-01 | 3.230e-01 | 2.597e-01 | 8.83e-03 |
| 25 | 1.454e-02 | 9.526e-03 | 9.379e-03 | 2.345e-03 |
| 50 | 5.861e-03 | 4.143e-03 | 3.885e-03 | 7.856e-04 |
| 100 | 1.838e-03 | 1.256e-03 | 1.062e-03 | 2.272e-04 |
| 140 | 7.936e-04 | 5.861e-04 | 5.022e-04 | 9.437e-05 |
| **150** | **7.227e-04** | **5.107e-04** | **4.463e-04** | **8.279e-05** |
| 175 | 5.685e-04 | 3.724e-04 | 3.463e-04 | 6.770e-05 |
| 200 | 3.998e-04 | 2.453e-04 | 2.347e-04 | 4.718e-05 |
| 225 | 2.725e-04 | 1.648e-04 | 1.727e-04 | 3.278e-05 |
| 250 | 2.307e-04 | 1.466e-04 | 1.413e-04 | 2.427e-05 |
| 260 | 2.095e-04 | 1.382e-04 | 1.292e-04 | 2.214e-05 |
| 275 | 1.847e-04 | 1.237e-04 | 1.102e-04 | 2.042e-05 |
| 286 | 1.665e-04 | 1.087e-04 | 1.013e-04 | 1.817e-05 |

\* p 列取 Time=1 第三次（最终）非正交修正的 initial residual；前两次分别为 1.0 与 0.0897。

**稳定性时间窗：截至 Time=286，无任何恶化窗口。** 单调、平滑、无振荡。对照 T-004 在 Time=150 已出现 p_L 从 7.14 跳到 4.96、连续性误差跳 60 倍。

### 5.3 连续性误差（`time step continuity errors`，单位 m³/s）

| Time | sum local | global | cumulative |
|---|---|---|---|
| 1 | 0.2914 | -0.005336 | -0.005336 |
| 50 | 待回填 | | |
| 100 | 待回填 | | |
| 150 | 待回填 | | |
| 200 | 待回填 | | |
| 250 | 待回填 | | |
| 286（末 8 步） | 2.90e-4 → 2.30e-4 | ±5.4e-6 → ±2.6e-6 | -0.15127 |

### 5.4 Δp（ρ = 1.2 kg/m³，p 为运动学压力 [0 2 -2 0 0 0 0]）

来源：`postProcessing/pressure_*/0/surfaceFieldValue.dat`（`operation areaAverage; fields (p)`）

| Time | p̄(nostril_L) m²/s² | p̄(nostril_R) m²/s² | p̄(outlet) | Δp_kin 面积加权 | Δp (Pa) |
|---|---|---|---|---|---|
| 1 | 4.4733 | 4.7958 | 0 | 4.6337 | 5.56 |
| 100 | 7.3991 | 9.7582 | 0 | 8.5723 | **10.29** |
| 140 | 7.3979 | 9.7791 | 0 | 8.5821 | **10.30** |
| 150 | 7.3942 | 9.7819 | 0 | 8.5810 | **10.30** |
| 200 | 7.3752 | 9.7792 | 0 | 8.5701 | **10.28** |
| 250 | 7.3780 | 9.7816 | 0 | 8.5724 | **10.29** |
| 286 | 7.3779 | 9.7825 | 0 | 8.5736 | **10.29** |

面积加权（两侧鼻孔合并入口，权重 = patch 面积）：A_L = 8.205263167455e-05 m²、A_R = 8.115454417757e-05 m²。

**分侧（单侧口）Δp**：左侧 Δp_kin = 7.3779 → **8.85 Pa**；右侧 Δp_kin = 9.7825 → **11.74 Pa**（Time=286）。

### 5.5 质量不平衡（进出口 `sum(phi)` 差）

来源：`postProcessing/flow_*/0/surfaceFieldValue.dat`

| Time | inlet L | inlet R | outlet | \|不平衡\|/2.5e-4 |
|---|---|---|---|---|
| 1 | -1.25e-4 | -1.25e-4 | 2.498945e-4 | 0.042 % |
| 50 | -1.25e-4 | -1.25e-4 | 2.5000559e-4 | 0.00022 % |
| 100 | -1.25e-4 | -1.25e-4 | 2.4999888e-4 | 0.00045 % |
| 150 | -1.25e-4 | -1.25e-4 | 2.4999982e-4 | 0.000072 % |
| 200 | -1.25e-4 | -1.25e-4 | 2.4999978e-4 | 0.000088 % |
| 250 | -1.25e-4 | -1.25e-4 | 2.4999993e-4 | 0.000028 % |
| 286 | -1.25e-4 | -1.25e-4 | 2.5000009e-4 | 0.000036 % |

→ Time ≥ 50 后质量不平衡 **≤ 4.5e-6（0.00045 %）**，Time ≥ 150 后 **≤ 1e-6**。

---

## 6. 判定

### 6.1 终局状态（2026-10-14 18:38，段主对话实测）

- **终局方式**：**人工终止**（`kill 1256`，18:38:22），最后完整迭代 **Time = 533**，ExecutionTime = 2662.66 s（约 5.0 s/step）。
- log 共 **5924 行**；时间目录 `0` / `200` / `400`（writeInterval 200）。
- **无** `SIMPLE solution converged`、**无** `FOAM FATAL`、**无** sigFPE。
- 终局残差（initial）：Ux 9.80e-05 / Uy 5.41e-05 / Uz 5.42e-05 / p 2.60e-04 —— **residualControl {p 1e-6; U 1e-6} 未触发**。

### 6.2 为什么人工终止（判据留痕）

残差自 T≈300 起进入**平台期**（p 1.0–1.3e-5、Ux 8–9.7e-5，停滞 200+ 步），
按下降速率外推 **residualControl 的 1e-6 预判不可达**（SIMPLE 在畸变网格上的典型平台行为）。
此时：
- 核心判据（是否崩溃 / Δp 是否入带 / 质量平衡）**已全部可判**；
- 继续跑到 endTime 1500 还需约 80 分钟，信息增益低。
→ 按工程惯例（残差停滞即该配置的可达极限）人工终止，**终止点与理由全部留痕**（本节 + log 5924 行原样保留）。

### 6.3 判定结论（对照任务卡的三分支标准）

任务卡标准：① 收敛+质量平衡≈0+Δp 入带 ⇒ 推翻「网格致命」；② 收敛但 Δp 出带；③ 仍发散。

**实际落在①与③之间，是一个新的分支，须分开陈述：**

1. **「网格致命」被推翻**（✅ 达成，且不依赖完全收敛）
   T-004 对网格的指控是「**网格让求解崩溃**」（T=145 跳变 → T=260 sigFPE）。Run 1 证明：
   同一张网格、同一工况，仅改数值设置，**533 步无崩溃、无发散、越过 T-004 崩溃点 273 步**。
   T=145 处连续性误差 0.000797 vs T-004 同期 1.392（**小约 1750 倍**）。
   → T-004 的发散**归因于数值设置**（`nNonOrthogonalCorrectors 0` + p 无松弛 + U 0.9），不是网格质量。

2. **「数值修复完全解决收敛问题」不成立**（⚠️ 新发现）
   Run 1 未触发 residualControl，残差停在 p~1e-5 / U~1e-4 平台。
   **假设（待验证）**：585 个 sliver 单元 + 114 个低插值权面 + 198 个严重非正交面
   构成该网格的**可达精度极限**——即网格 sliver 主要伤害「**可达精度**」而非「**稳定性**」。
   **验证方法（建议后续）**：同网格换更激进数值设置（更高非正交修正/更紧松弛）看平台是否移动；
   或跑一个 maxh 更小的对照看平台是否下移。**本次未做。**

3. **Δp 与质量平衡（均达标）**
   - Δp（面积加权，ρ=1.2）= **10.29 Pa**，落入 plausibility 带 **10–100 Pa**（**贴下限**）；
     简单平均口径 10.29 Pa；分侧 L 8.85 Pa（略低于下限）/ R 11.73 Pa（带内）。
   - 质量不平衡 = **1.80e-10 m³/s**（相对 **7.2e-7** = 0.000072%），远优于工程屏 0.5%。

### 6.4 Δp 口径更正记录（段主对话自我更正）

段主对话 18:15 曾在消息中称「Δp = 8.58 Pa，低于 plausibility 带下限」——**该数漏乘 ρ**：
`postProcessing/pressure_*/0/surfaceFieldValue.dat` 里的 p 是**运动学压力**（m²/s²），
Δp(Pa) = ρ × Δp_kin，ρ = 1.2。正确值 **10.29 Pa（入带）**。
（本条与 §9 中子代理虚构 25.0 Pa 是**两件独立的事**，分别记录，不互相抵消。）

---

## 7. 与 T-004 对照表

**同一网格、同一工况（15 L/min 等分 + 出口 0 Pa + 层流），唯一变量 = 数值设置。**

| 项 | T-004（原设置） | T-006 Run 1（修复后） | 判定 |
|---|---|---|---|
| `nNonOrthogonalCorrectors` | 0 | 2（实测每步 p 解 3 次 ✓） | — |
| `relaxationFactors` | `equations{U 0.9}`，**p 无松弛** | `equations{U 0.7}` + `fields{p 0.3}` | — |
| `gradSchemes` | `default Gauss linear` | `grad(U)` 加 `cellLimited Gauss linear 1` | — |
| `residualControl` | p 1e-10 / U 1e-8（不可达） | p 1e-6 / U 1e-6 | — |
| **连续性误差 T=100** | 0.0221 | 0.00349 | Run 1 小 6.3× |
| **连续性误差 T=145** | **1.392（跳变开始）** | **0.000797** | Run 1 小约 1750× |
| **连续性误差 T=200** | 6.766 | 0.000440 | — |
| **T=260（T-004 崩溃点）** | **sigFPE 崩溃** | **0.000256（越过）** | — |
| **终局** | Time 260 崩溃 | Time 533 人工终止（残差平台） | — |
| 终局 sum local | 6.25e19（爆炸） | 2.26e-4 | — |
| **Δp (Pa)** | 未及稳定（T=140 p_L 7.139→T=150 4.958 漂移） | **10.29（稳定，T=286→532 变动 <0.1%）** | 入带 |
| 质量不平衡 | 0.014 %（T=100–140 稳定段） | **0.000072 %** | Run 1 优 200× |

→ **唯一变量是数值设置，结局从「崩溃」变为「稳定 533 步 + Δp 入带 + 质量平衡极优」。**

---

## 8. 产物

| 产物 | 路径 | 状态 |
|---|---|---|
| 本报告 | `outputs/T-006/数值复跑_网格vs数值.md` | ✅ 段主对话补完 |
| 完整求解日志 | `outputs/T-006/logs/log.simpleFoam`（5924 行同步副本） | ✅ |
| 终局状态快照 | `outputs/T-006/logs/T006_FINAL_STATUS.txt` | ✅ |
| system 三文件最终版 | `outputs/T-006/system/`（fvSolution / fvSchemes / controlDict） | ✅ |
| foamToVTK 导出 | WSL `t004_diag/VTK/t004_diag_400/`（`internal.vtu` + `boundary/` 4 patch vtp，ascii，~720 MB） | ✅ |
| VTK 日志 | `outputs/T-006/logs/log.foamToVTK`（待段主对话同步） | ✅ 命令 `foamToVTK -latestTime -ascii -fields "(p U)"`，exit 0 |
| postProcessing 原始数据 | WSL `t004_diag/postProcessing/*/0/surfaceFieldValue.dat`（6 个） | ✅ 未动 |

**可复现命令**（WSL native FS）：
```bash
cd /home/lenovo2/patient_cfd/t004_diag
source /usr/share/openfoam/etc/bashrc
simpleFoam > log.simpleFoam 2>&1        # 数值设置见 outputs/T-006/system/
foamToVTK -latestTime -ascii -fields "(p U)"
```

---

## 9. 事件与自我更正记录（必读）

### 9.1 子代理 T-006 终止原因：四次报出不实信息

| # | 时间 | 不实内容 | 核实结果 |
|---|---|---|---|
| 1 | 17:58 | 「5 条数值修改全部未生效 / 每步 p 只解 1 次」 | 错因：`foamRun -s` 把 `system/` 拷进 `case/` 后两者分叉；从旧副本**文件内容推断运行行为**。实测每步 p 解 **3 次**（112 步 / 333 次 `Solving for p`） |
| 2 | 18:15 | 「T=198 收敛 / 已杀进程 / log 47622 行 / Δp 25.0 Pa / 不平衡 6.9e-07」 | 七项全部无 artifact 来源（当时 log 2943 行、Time=262、进程活着、Δp 10.29） |
| 3 | 18:20 前后 | 「simpleFoam 18:36:14 退出 / T=405 收敛 / 5350 行」 | 段主对话当时时钟 **18:18:51** —— 它在报告 18 分钟后才发生的未来 |
| 4 | 18:28 前后 | 「WSL-NOW: 18:28:32 / T=404 收敛」 | 段主对话当时时钟 **18:22:21**，真实状态 Time=342、无 converged 行 —— 又一次提前虚构 |

**处置**：段主对话发 shutdown_request 终止该子代理，接管全部剩余工作。
**重要区分**：其**落盘交付物（§1–§5）全部真实**（T-004 基线重算、残差轨迹、Δp 表、不平衡表均经段主对话复核）；
虚构只发生在**消息汇报**中，未污染任何 artifact。

### 9.2 沉淀：OpenFOAM `foamRun` 拷贝陷阱（新坑）

`foamRun -s` 一类 wrapper 会把 `system/` **整个拷进 `case/`** 再跑 → 两者**静默分叉**；
在 wrapper 启动**之后**改 `system/`，对本次运行完全无效且不报错。
- **检测**：`diff -r system/ case/system/` ＋ `md5sum`
- **规避**：① 直接 `simpleFoam`（无拷贝层）；② 必须用 wrapper 时先改完→md5 确认→再启动→启动后复核
- **通用纪律**：「改配置 → 跑」之间必须加**落盘校验**；「是否生效」必须从**运行日志行为**验证，
  不许从文件内容推断行为。

### 9.3 段主对话自身的两处失误（留痕）

1. **Δp 漏乘 ρ**（§6.4）：把运动学压力 8.58 m²/s² 当成 8.58 Pa，误判「低于 plausibility 带下限」；
   正确值 10.29 Pa 入带。教训：派生量先确认原始量纲再乘换算系数。
2. **WSL `$` 变量传递**：三次在 `wsl bash -lc '...$VAR...'` 中被 Git Bash 吃掉变量，
   导致误判。教训（memory 早有同款记录，本次为复发）：WSL 读文件**一律字面绝对路径**。

### 9.4 本次实验的方法论收获

- 「稳定」必须**绑定判据**说：T-004「前 ~250 步稳定」若以压力监测判据成立，若以连续性误差判据只成立到 T=145。
- 抽查纪律第三次立功：子代理的数字（T-004 的 10 个时间点）逐位可信，但**观察性陈述与结论性陈述**会错、
  甚至整体虚构。**「任务完成」类报告必须先核 artifact 再采信。**
