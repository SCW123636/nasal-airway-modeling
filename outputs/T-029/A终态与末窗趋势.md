# T-029 A 有界试验终态与末窗趋势

本文件是执行体交付，供 Lead/T023 判约；不自授 VERIFIED/CLOSED。

## 实际运行与终态

- 正式 8769 单次 POST：`s_aa79a63027b94bfb9a273898`，`b15_engineering_t029a`，2026-10-15 19:40:57+08 创建、19:52:15+08 终态 `failed`，外层退出码 1。
- 新 native 隔离 case：`/home/lenovo2/nasal_cfd_workspace_jobs/s_aa79a63027b94bfb9a273898/evaluations/eval_001`。原失败任务/旧输入不覆盖、不续跑。
- 实际 `checkMesh`、`simpleFoam`、`foamToVTK` 均返回 0；120 个完整迭代与 120 个监测样本，日志有 `End`、无实际 FPE、无 SIMPLE convergence banner。底层执行成功与数值质量通过分别记录，外层质量拒绝不能改为成功。
- 数值方案唯一试验变量：U 对流由 `bounded Gauss linearUpwind grad(U)` 改为 `bounded Gauss upwind`。运行预算为 endTime=120、writeInterval=20。共同入口静压10 Pa、出口0 Pa、rho=1.2、物性/边界/网格/松弛/非正交修正次数及质量门不变；未强加流量或左右分流比例。
- 新输入、原输入、冻结源码在收集时逐文件 SHA 一致；实际 12 项 polyMesh 与冻结输入一致。`t029a_actual_result.json` 含原始小文件副本索引、大字段/VTU 内容哈希与逐项检查结果。

## 同步数值与趋势

| 指标 | 原失败基线120 | A120 |
|---|---:|---:|
| continuity local（日志原定义） | 27.3757836295 | 1.03973269892 |
| Qout（m³/s） | 0.01370741232816 | 0.003509777823132 |

A120 的 signed nostril_L=-0.0009647637636626 m³/s、signed nostril_R=-0.002549370312534 m³/s；global continuity=-0.220358388408。U initial residual max=0.0266717823903，第一次 p initial residual=0.0718662144839，最后/第三次 p initial residual=0.00426929103623。三次压力内迭代分开保留，不以最后一次替代第一次来隐藏收敛状态。

| A 末窗 | continuity local OLS/步 | local 后10/前10均值 | Qout OLS（m³/s/步） | Qout 后10/前10均值 |
|---|---:|---:|---:|---:|
| 101–120 | 0.02879407377587368 | 1.4210239106393443 | 8.146545858170978e-5 | 1.3638150561116824 |
| 81–120 | 0.015553454319472325 | 1.9988608089249185 | 5.680000253518452e-5 | 2.2773666744579826 |

统计公式是 `Σ((x−均值x)(y−均值y))/Σ((x−均值x)²)`，不依赖截距；窗口完整且无缺失。对数 OLS 仅对正样本作描述性拟合，不作预测或指数发散机理证明。`analyze_late_windows.py` 从保留的两份实际 timeline 重算并与既有 `late-window-trends.json` 全结构精确比较，已知答案及输入/脚本/结果 SHA 在 `late-window-reproduction.json`。首次复现只在4个等长十样本比值末位出现约2e-16差异：原计算先约去相同样本数，以后10之和/前10之和求值；复现脚本现保留此浮点顺序，首次差异保存在 `late-window-reproduction-first-failure.json`，既有趋势证据未改。

结论：A 的同120步误差比原基线小，且未出现原基线223步的 FPE；但末段流量、连续性及残差仍未稳定，现有质量门拒绝。不能称稳定/收敛，不能自动延长至300，也不能用这个失败点参与压力反馈或宣称患者15 L/min已求得。尚未证明唯一数值根因。

## 检查器更正与实际场导出

- 首版进度检查器误将启动行 `Floating point exception trapping enabled` 当 FPE。保留首版工具、首版快照与原始日志，新增 v2 工具和快照。旧首版快照中的 FPE 布尔值无效；不改写其原始状态/数值。
- v2 正则排除 `trapping`，并以旧任务实际 `Foam::sigFpe::sigHandler` 栈作正控制、A 的正常 trap header 作负控制。证据：`fpe-extraction-v2-known-answers.json`。
- VTU 已真实生成，但仅为未收敛诊断场；附加 viewer exporter 实际错误为“抽取后存在退化三角面”。原 A job/report 不回填，T024 另卡修复并独立验收。

## 复现与下一依赖

在项目根目录，用项目 Python 执行 `outputs/T-029/analyze_late_windows.py` 即可只读复核末窗，不启动求解。终态提取逻辑为 `collect_trial_result_v2.py`，它冻结证据并核指纹；旧 case 与原始输出不改。

B 仅零 CPU 准备：保留 A 的 upwind，只评估带版本来源的显式非正交修正限制。必须解释实际字典作用路径、以新身份/输入冻结并经 Lead 判约。B 的最终生产源码冻结等待 T024 最小修复或明确不改结论；尚未 POST、尚未运行 B。
