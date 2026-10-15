# 20261015 · T-038 SimVascular / Slicer-VMTK 路线核验

- 来源任务：`tasks/T-038.md`；证据：`outputs/T-038/SimVascular_SlicerVMTK可行性核验.md`（含全部复现命令）。
- 车道与级别：零 CPU / T1；未碰患者数据、未改生产代码、未动 Slicer 安装目录。
- 触发：用户 `simvascular`（21:08）→ 段主三方向判断 → 用户 `changshi`。

## 核验到的事实（本机）

- **3D Slicer 5.12.4（rev 34645）确实已装**，实际路径 `D:\项目\鼻腔建模\软件\slicer\3D Slicer 5.12.4\`（注册表 `DisplayIcon` 指向的旧路径 `软件\新建文件夹\...` 已失效）。→ **段主 21:08 所说「T-019 记录需复核」现修正为：T-019 记录属实。**
- **已装扩展 = 0 个**：`slicer.org/Extensions-34645/` 为空目录，两个 ini 的 `[Extensions]` 段均无扩展条目。
- 扩展服务已配置可用：`slicer-packages.kitware.com`（Girder_v1）+ `extensions.slicer.org`，`ManagerEnabled=true`；服务器 HTTP 可达。
- 历史上 Slicer 用过 10 次（2026-09-28 ~ 10-05），曾加载 `NasalSeg_P001_Slicer.mrml`（P001，spacing z=1.5mm）。

## 外部核验

- 官方论坛（SlicerHeart/CHOP + SimVascular/Stanford）明示：模块「available via the VMTK and SimVascular extensions for the latest Slicer Stable Release (**currently Slicer-5.12.4**)」→ 与本机版本逐字对上。
- SlicerVMTK 提供 `Extract Centerline` / `Clip vessel` / `CFD Mesh Generator`（三引擎 TetGen / **NetGen(LGPL 免费商用)** / fTetWild，支持 capping + 表面重网格 + **可选棱柱边界层**）。
- **不利证据（关键）**：`Clip Vessel` 官方 README 要求"All branches/vessels should contain a centerline"；作者在论坛承认**平行/紧邻管道会失效**（"tubes are almost parallel … could be problematic"）。鼻腔 = 单一腔体 + 左右两条平行通道 + 鼻甲分腔，**正是该已知失效形态**。

## 判定

- ④ 求解器（`svMultiPhysics`）：**不建议替换**。M1/M2 裁定 + `cfd_contract` + T-004/T-006/T-008/T-010 全绑 OpenFOAM，换 = 已付成本清零；FSI/0D 耦合非当前刚需。
- ③ 体网格（`CFD Mesh Generator`）：**值得实测**。可独立吃现有 STL（不依赖裁剪）；NetGen 内核与现选一致，额外给边界层 + 面标签传播。
- ② 开口裁剪（`Clip Vessel`）：**谨慎**。硬限制与鼻腔形态重叠；需先验证气道中心线。
- ① ML 分割：无必要。

## 未验证 / 边界

- 本机未装任何扩展，"能否装、装上能否跑"未实测；Girder API 路由未命中（400），扩展包下载 URL/体积未确认。
- `CFD Mesh Generator` 输出格式 → OpenFOAM `polyMesh` 的转换路径未验证（可能工作量最大）。
- 单位风险：Slicer mm-g-s vs 本项目 STL 为米。
- 项目规矩不变：任何候选网格仍须过本地 `checkMesh` 四门禁，**不得绕过 N6**；本路线不解决表面自交问题。

## 交接

- 待用户裁定：A 授权装扩展跑试验 1（解析圆管 + NetGen + 边界层 → checkMesh）｜B 仅登记候选｜C 并入 T-019 参考链路（SimScale 替代）一起裁定。
- 执行体不授予 `VERIFIED`/`CLOSED`；本卡由段主自验并已记 VERIFIED，fresh 独立验证未安排（T1 级、无患者数据）。
