# T-058 独立验证报告（fresh subagent，只读产物）

- 验证者：`agent-5b75da3d-a7ca-4b73-bfcf-757446247b71`（general-purpose，未参与本任务创作）
- 时间：2026-10-16 12:1x
- 方式：只读 `outputs/T-058/` 与 `C:/ts_work/t058_chain_anat/`、`t058_oroext_opening_anat/`，不信任任何转述，主动找反证
- 范围：T-058 三例全链（解剖斜切）患者指标数值真实性 + 工作台接入回执

## 总体结论

**主张基本成立**：Δp/R、WSS 合力、M2 四判据、相对轴位百分比、鼻孔回归、网格门、工作台接入 **七项核心数值均能从交付 JSON/日志独立复现或交叉印证**；Δp 正确含 ρ=1.2、单位自洽、**未现伪造迹象**。

## 逐条核验

| # | 主张 | 结果 | 证据 |
|---|---|---|---|
| 1 | 三例 Δp / R | **PASS** | `metrics_t058_*.json` → `metrics.delta_p_pa.value` / `metrics.resistance_R.value_pa_s_ml`：b15 17.119542/0.068478、b01 15.460361/0.061841、b02 43.230504/0.172922 |
| 2 | 三例 WSS 合力 | **PASS（含方法学注记）** | `wss_t058_*.json` → `wall_shear_force_n`：0.0014854506 / 0.0012736585 / 0.0023701889 |
| 3 | M2 四判据 + 不平衡≤1e-6 + monitor≤1% | **PASS（阈值注记）** | `m2_criteria` 四字段全 true；`mass_imbalance_frac` 6.02e-8/4.48e-7/4.58e-7；`monitor_max_window_change_frac` 1.111e-4/1.000e-4/7.633e-4 |
| 4 | 相对轴位基线百分比 | **PASS（独立重算）** | b15 (17.119542−18.267)/18.267 = **−6.2814%**；b01 (15.460361−15.709)/15.709 = **−1.5828%**；与 `reconciliation.delta_p_pa.rel_diff` 一致 |
| 5 | 鼻孔回归 ≤0.01 mm² | **PASS** | `anat_chain_verification.json` → `nostril_regression`（b15 Δ−0.0026/−0.0027、b01 +0.0026/+0.0011、b02 −0.0005/+0.0040，全 match=true） |
| 6 | 网格门 b15 失败项 ≤3 | **PASS（基线本次已补）** | `checkMesh.log` 第 111 行 `Failed 2 mesh checks.`；轴位切基线 3 项本次补归档 `checkmesh_axial_t054_b15.log` |
| — | 工作台接入 | **PASS** | `pro_workbench_check.json`：`all_ok=true`、`pageerrors=[]`、`console_errors=[]`；三例 `ok=true` 且 `prop_has_manifest/prop_has_metrics=true` |

## 关键反证与口径澄清

1. **Δp 未漏乘 ρ**：JSON 含 `rho_kg_m3: 1.2`，且 Δp = 双侧 inlet 运动学压力均值 × 1.2 精确成立
   （b15 `(14.075732+14.456838)/2 × 1.2 = 17.11954`；b02 `(43.427521+28.623320)/2 × 1.2 = 43.23050`）。✅
2. **WSS 合力 ~5% 偏差系表示法差异，非造假**：验证者从 `C:/ts_work/t058_chain_anat/{case}/wall_600.vtp` 用
   VTK 重算合力（ρ×Σ|τ|·dA，顶点均值法）得 b15 0.001415 / b01 0.001219 / b02 0.002245，比 JSON 低约 5%；
   但**面积重算与 JSON 完全一致**（0.018797226 m²）→ 几何、量级、覆盖率均正确，偏差源于 OpenFOAM **面**基场
   转 foamToVTK **点**数据时的平滑。
3. **WSS max 同源于面/点表示法**：`wss_max_pa`（b15 3.488 / b02 22.8646）无法从点数据 VTP 复现峰值
   （VTP 点最大模偏低），但 b02 `log.wss` 面场极值矢量模约 20.99（kin）×ρ 后与 22.86 同量级，属预期。
4. **cells 两套口径（内部差异，非矛盾）**：`metrics.domain.mesh_cells_repaired`/`mesh_anat.tetrahedra` = netgen 生成数
   （639686），`checkMesh.cells`/log = gmshToFoam 后数（653789）；`reconciliation.cells.now` 用同一口径，内部一致。
5. **单位自洽**：`mesh_anat` 用 mm²、`wss` 同时给 m² 与 mm²（0.018797226 m² = 18797.226 mm² 自洽）、`metrics` 用 Pa/m³/s
   ——未发现 mm²/m² 错配。

## 保留的边界（须随数值引用）

- 三例 `metrics.converged = false`；`numerical_validation = "unchecked (per M2 ruling; final residuals recorded)"`。
  **M2 四判据不含 residual 1e-5 门**（字段名为 `..._le_0.5pct`，即 0.5%/0.5%），故残差高不影响 M2 PASS。
- **b02 弱收敛**：残差 Ux=1.718e-3 / p=2.089e-4，三例最高 → 引用 b02 数值时须带此状态。

## 未能核验项 → 本次已闭环

- **「轴位切基线 = Failed 3」** 在 T-058 交付物中此前无对应文件，基线值本身无法核验 → 本次已补
  `outputs/T-058/checkmesh_axial_t054_b15.log`（cells 636342、non-orth max/avg 76.7999/18.8539、
  >70° 面 94、det<0.001 单元 466、**Failed 3 mesh checks**）。不等式 2 ≤ 3 成立。

## 验证者明确未做

- 按「只读」要求，未重跑 playwright（工作台接入仅核对现有回执 JSON）；未运行任何求解/网格命令。
