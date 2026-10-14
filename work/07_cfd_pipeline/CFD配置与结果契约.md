# CFD 配置与结果契约

当前交付只有工程配置、校验代码及合成回归测试。没有生成患者流场，没有运行患者 CFD，也没有把任何几何审核改成 confirmed。`configs/` 中 8 个配置都可通过结构/数值校验，但都明确禁止执行：患者几何待审核，求解器适配层尚未实现和验证。

## 文件与接口

- 实现：`work/lib/cfd_contract.py`
- 回归测试：`work/lib/test_cfd_contract.py`
- 配置目录：`work/07_cfd_pipeline/configs/`
- 配置清单及逐项验证状态：`work/07_cfd_pipeline/config_catalog.json`
- 配置 schema 标识：`nasal_cfd_config/v1`
- 结果 schema 标识：`nasal_cfd_result/v1`

这里的 schema 字符串是项目契约版本。可执行校验由 Python 函数实现，不声称这些 JSON 文件已经通过某个未提供的外部 JSON Schema 文件验证。

```python
validate_config(config, require_execution_ready=False)
validate_result(result, config=None)
pressure_to_pa(values, source_unit, rho_kg_m3=None, source_field="p")
compute_turbulence_intensity(
    velocity_m_s, k_m2_s2=None, model="laminar",
    low_speed_threshold_m_s=None,
)
flow_lpm_to_m3_s(value)
inlet_mean_speed_m_s(flow_m3_s, area_mm2)
```

两个校验函数返回 `valid / errors / warnings / execution_allowed / validation_scope`。`valid=true` 只表示契约检查通过。患者模板可以合法但不能执行。`validate_result()` 不授予求解权限，其 `execution_allowed` 固定为 false。

`pressure_to_pa()` 返回标量或普通列表。`compute_turbulence_intensity()` 对层流返回 Python `None`，序列化后即 JSON `null`；对 SST 返回带 `values` 和 `valid_mask` 的字段对象。转换函数遇到非法输入抛出 `ContractError`。

## 8 个配置

| 配置 | 工况 | 说明 |
|---|---|---|
| `total_flow_laminar_coarse` | 总目标 15 L/min，鼻咽(nasopharynx)静压 0 Pa，层流，粗网格 | 主腔初值 0.6 mm |
| `total_flow_laminar_medium` | 同上，中网格 | 主腔初值 0.4 mm |
| `total_flow_laminar_fine` | 同上，细网格 | 主腔初值 0.275 mm |
| `total_flow_laminar_medium_equal_split_baseline` | 左右各 7.5 L/min，鼻咽静压 0 Pa | 人为等分对照，不能报告为患者分流 |
| `total_flow_kOmegaSST_medium_I01` | 总目标 15 L/min，SST 入口湍流强度 1% | JSON 存储 0.01 |
| `total_flow_kOmegaSST_medium_I05` | 总目标 15 L/min，SST 入口湍流强度 5% | JSON 存储 0.05 |
| `static_pressure_difference_laminar_medium` | 鼻孔静压 0 Pa，鼻咽静压 −18 Pa | 静压差 +18 Pa，流量由求解产生 |
| `recording_total0_staticplus18_laminar_medium` | 鼻孔总压 0 Pa，鼻咽静压 +18 Pa | 录屏原字段复现，必须先检查有符号流量方向 |

所有压力配置都明确记录 `quantity=static/total`、`reference=gauge`、`unit=Pa`。密度为 `1.2 kg/m3`，动力黏度为 `1.81e-5 Pa s`，是 20°C 近似工程输入，尚需项目实际工况回测。

总流量 15 L/min 等于 `2.5e-4 m3/s`。允许两侧由几何阻力决定分配的预定适配策略是 `common_inlet_pressure_feedback`：两个鼻孔使用共同待调整静压，出口静压 0 Pa，由外层迭代调共同入口压力以匹配总流量目标。流量是外层目标，不能再同时成为该压力求解的 PDE 流量边界。该适配器当前 `not_implemented`，没有写入或假设某个不存在的 OpenFOAM“联合流量边界”。把两鼻孔合成一个 `flowRateInletVelocity` 面也不能直接当成自然分流证据。

固定流量配一个出口静压参考，本身是有效边界组合；出口参考从 0 Pa 改成 +18 Pa 并不自动造成过约束。这里禁止的是同一工况既固定总流量，又同时规定两端压力差/入口压力。上述区分优先于旧 `18Pa溯源.md` 中曾出现的“一切流量+18Pa都过约束”口径。

鼻阀(nasal valve)、鼻甲(turbinate)间隙、嗅裂(olfactory cleft)的局部网格必须满足 `h <= min(初始局部尺寸, 实测间隙/6)`。粗/中/细局部初值为 0.30/0.25/0.20 mm，不能据此推断细小通道已经充分解析。SST 模板使用 10 层棱柱层、增长率 1.2、总厚度初值 0.75 mm；首层高度仍须由计算结果回算，并检查 y+。

## 结果类型

| `type` | 可以展示 | 不能声称 |
|---|---|---|
| `patient_preview` | 患者分割表面和空间位置 | 已有患者流速、压力或湍流解 |
| `analytic_reference` | 非患者理想几何的解析场，用于验证显示和单位 | 患者预测或数值 CFD 求解结果 |
| `cfd_result` | 有求解器、版本、运行日志、配置与诊断记录的实际流场 | 仅凭求解完成就取得临床验证 |

所有结果的 `fields` 必须明确包含 `velocity`、`pressure`、`turbulence_intensity`。患者预览三项都必须为 `null`。解析参考的 `geometry.kind` 必须是 `idealized`，`case_id` 必须为 `null`，并在 `provenance` 写明 `method=analytic_solution` 和解析方程。

非预览流场的 `physics` 必须记录 `turbulence_model`、`rho_kg_m3`、`mu_Pa_s`。层流 `turbulence_intensity` 必须为 `null`，`turbulence_intensity_status=not_applicable`。填充 0% 的层流湍流图层会被拒绝。

常规字段格式如下：

```json
{
  "velocity": {
    "unit": "m/s",
    "association": "point",
    "values": [[1.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
  },
  "pressure": {
    "unit": "Pa",
    "association": "point",
    "quantity": "static",
    "reference": "gauge",
    "source_unit": "Pa",
    "source_field": "p",
    "values": [0.0, -1.0]
  },
  "turbulence_intensity": null
}
```

上面只是字段结构示例，不是患者结果。`association` 支持 `point` 或 `cell`；速度为 N×3 向量，压力为 N 个标量。同一关联位置上的速度/压力长度必须一致。也可用 `data_file` 替代 `values`，二者只能选一个；此时契约检查只检查元数据，不会假称已经核验外部数组，导入器还须加载并验证实际数组。

## 湍流强度和 OpenFOAM 压力

SST 使用显式定义 `I = sqrt(2*k/3) / magnitude(U)`，内部单位是无量纲比例 `1`，百分数显示时再乘 100。当前低速显示遮罩初值为 `0.05 m/s`，写在每个字段的 `low_speed_threshold_m_s` 中；`|U| <= 该值` 的 `values` 为 `null`、`valid_mask=false`。这个阈值是显示层工程假设，应检查改变阈值后结果解释是否变化，不能当作已由患者数据验证的判据。负 k、非有限 U/k 或未指定遮罩阈值会被拒绝。

不可压缩 OpenFOAM 的压力输出必须核对维度后处理：当源字段单位是 `m2/s2` 时，`p[Pa] = rho[kg/m3] * p_kinematic[m2/s2]`。必须显式提供密度；不得只凭字段名 `p` 猜单位。原单位已经是 Pa 时不再乘密度。这个转换不改变表压零点，不把静压改成总压。

转换后的压力记录 `source_unit=m2/s2`、`rho_kg_m3` 和 `conversion="p_Pa = rho_kg_m3 * p_kinematic"`。`p_rgh` 含有静水压修正问题，本模块明确拒绝直接当 p 密度缩放；须先完成明确的静水压重建再传入。

## 患者正式 CFD 门禁

`cfd_result` 的患者几何必须具备 `review.status=confirmed`、`review.method=human`、审核人/时间/记录文件、与几何一致的 SHA-256、左右鼻孔和鼻咽出口确认，以及口腔排除和鼻窦(paranasal sinus)边界策略确认。缺少任一项会被拒绝。

真实 `cfd_result` 还必须有 `solver_name`、`solver_version`、`run_id`、`run_log`、`config_id`，记录实测质量不平衡、末段监控量变化和残差。它必须明确 `numerical_validation` 是 `unchecked`、`failed` 或 `passed_engineering_screen`；声明通过却超过工程门槛会被拒绝。

审核元数据检查不认证审核人的身份，也不验证外部文件真实性。后续执行器必须实际核验审核记录来源、文件哈希和几何质量，不能通过自行填写 confirmed 来绕过人工审核。当前所有模板仍是 pending，也未实施该执行器。

## 诊断量取值口径

工程屏值（`maximum_mass_imbalance_fraction`、`maximum_monitor_relative_change`、`target_residual_max`、`medium_to_fine_change_screen_fraction`）一律不改；本节只定义两个诊断量“取哪个值”，不改判据。两个口径也写入 `make_config()` 生成的 `engineering_screen.diagnostic_basis`，机器可读，与本文档一致。

### `mass_imbalance_fraction`

- **取值口径**：取**稳态段（末段样本窗）**的 `mass_imbalance_fraction` 作为工程屏比较值。
- **启动瞬态单独列示、不计入屏**：初始场不无散会制造启动假象。T-006 Run 1 全程 max **6.3324e-03 发生在 t=2**（启动瞬态）；t≥100 已 ≤6.78e-6、稳态段 ≤1.74e-6、终值 7.2e-7。启动瞬态峰值只作为过程记录，不参与 `maximum_mass_imbalance_fraction`（0.005）屏判定。
- **理由**：初始场不无散是离散化启动假象，不是求解缺陷——但**绝不因此放松 0.5% 屏值**。若契约隐含“取全程 max”，会把初始场假象误判为求解缺陷，使 Run 1 错误“不通过”。

### `monitor_relative_change`

- **定义**：监控量取 **Δp = 面积加权鼻孔均值静压 − 鼻咽出口静压**。
- **取值口径**：取 Δp 的**窗间相对变化**；对**末 40% 样本**、**窗长 20** 逐窗取窗口均值，再取相邻窗口均值的比值的 **max**。
- **实测**：T-006 Run 1 该值为 **0.0079%**，远小于 `maximum_monitor_relative_change`（0.005）屏——注意此屏以“分数”定义（0.005 = 0.5%），0.0079% = 7.9e-5，仍处于屏内。口径定义不随本次实测放松任何屏。

## 使用

```powershell
& 'C:\Users\lenovo\.workbuddy\binaries\python\envs\nasal-cfd\Scripts\python.exe' 'D:\项目\鼻腔建模\work\lib\test_cfd_contract.py'
& 'C:\Users\lenovo\.workbuddy\binaries\python\envs\nasal-cfd\Scripts\python.exe' 'D:\项目\鼻腔建模\work\lib\cfd_contract.py' --write-templates
```

校验单个模板可使用 `--validate-config 文件路径`；加 `--require-execution-ready` 检查执行门禁。校验结果用 `--validate-result 文件路径`，可同时传入 `--validate-config` 验证结果与配置一致性。输出 `valid=false` 时退出码为 1。

事实来源为 `work/04_cfd_ready/CFD参数裁定与回测清单.md` 及录屏原字段的项目溯源；参数仍是待真实病例回测的工程起点。合成测试只验证单位、约束、字段和门禁行为，不验证医学准确率或 CFD 收敛。
