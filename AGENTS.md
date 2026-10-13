# AGENTS.md · nasal-cfd 项目指令文件

> 本项目以 skill `collaboration-protocol` 为**多对话协作主协议**，以 skill `project-protocol` 为**单步纪律层**。
> 全局铁律已在 `~/.workbuddy/MEMORY.md` 的「全局工作规则」节每次注入，此处**只写本项目独有信息**。
> ⚠️ 本机**未核验**「打开项目自动读取本文件」机制；在核验通过前，本项目规则仍以 `MEMORY.md` + skill 为准，本文件作**备份载体**。

## 这个项目是什么

`nasal-cfd`（小隼）：给一个空鼻症患者上传的 CT 原片，**自动**产出可直接进 CFD 的鼻腔气道 STL，并跑通体网格→求解。
主档案：`~/.workbuddy/project-files/nasal-cfd/PROJECT.md`（样板档案）。工作区：`D:\项目\鼻腔建模\`。

## 黑板（唯一事实源）

| 目录 | 谁写 | 说明 |
|---|---|---|
| `plan/` `state/` | **仅段主对话** | 主计划 + 状态；会被反复加载，保持小而结构化 |
| `tasks/` | 卡片归其负责对话写 | 每张卡只写自己的状态与验收记录 |
| `outputs/T-<编号>/` | 该卡执行对话 | 内部结构自行判断；收工写结论卡 |
| `knowledge/` | 段主对话 | 结论卡 + 项目内沉淀（打法/模板/踩坑） |
| `research/` | 段主对话 | 云端任务包回收落点 |

## 本项目硬约束（踩出来的）

1. **只用** `work/lib/dicom_sitk.py::load_series_sitk` 读 DICOM（SimpleITK，解 JPEG Lossless P14）；`SliceThickness` 不可信，Δz 由 IPP 沿法向反算。
2. **阈值/压力口径未定**：−300（备 −350/−400）、出口 0 Pa（18 Pa 是 SimScale gauge 静压、**非 Δp**，作者确认前不用）。
3. **所有判据先用「带出处的已知答案」验证**——本项目已 6 次出现「判据输出合法但与事实不符」。
4. **WSL 场景要真实 artifact / 时序**：禁止编造数字；OpenFOAM case 建在 native Linux 文件系统，**不要** `cd /mnt/c` 再跑。
5. **git**：谁有权写谁提交，只 `git add` 自己权限内的路径；**禁止 `git add .` / `-A`**；提交信息 `[T-编号] 主题`。`.gitignore` 必含 `.workbuddy/`。
6. 医学/解剖判断**不由本地卡做**，需复核人（王湧瑞）。

## 方法库

- 路径：**未指定**（协议要求由用户提供；当前按「无库」走）。指定后写进本文件。
