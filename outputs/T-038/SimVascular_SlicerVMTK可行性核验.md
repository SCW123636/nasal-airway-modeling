# SimVascular / Slicer-VMTK 路线可行性核验

- 任务卡：`tasks/T-038.md`
- 执行：2026-10-15 22:17–22:25（段主对话亲自执行，零 CPU 车道）
- 触发：用户指令 `simvascular`（21:08）→ 段主三方向判断 → 用户 `changshi`（尝试）
- 声明：本报告不含患者数据、未改动任何生产代码或 Slicer 安装目录

---

## 0. 一句话结论

**SimVascular 的求解器（svMultiPhysics）不建议替换我们现有的 OpenFOAM 链；但同源的 `3D Slicer + VMTK/SimVascular 扩展` 里的体网格生成器（NetGen 引擎 + 边界层）值得实测，因为它能直接吃我们现有的 STL 而不依赖裁剪环节。而这条路线里看起来最诱人的 `Clip Vessel`，有一条官方明示的硬限制与鼻腔几何形态直接冲突。**

---

## 1. 本机软件事实（已实测取证）

| 项         | 事实                                                                                                                                                                                           | 证据来源                                                                                                              |
| --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Slicer 版本 | **3D Slicer 5.12.4**（revision 34645）                                                                                                                                                         | 注册表 `DisplayName`/`DisplayVersion`；`Slicer.ini` `LatestReleaseRevision=34645`                                     |
| 安装位置      | `D:\项目\鼻腔建模\软件\slicer\3D Slicer 5.12.4\Slicer.exe`                                                                                                                                           | 实测 `find` 命中；注册表 `DisplayIcon` 指向的旧路径 `软件\新建文件夹\...` **已失效**（目录被重组过）                                              |
| **已装扩展数** | **0 个**                                                                                                                                                                                      | 安装目录 `slicer.org/Extensions-34645/` 为**空目录**；`Slicer.ini` 与 `Slicer-tmp.ini` 的 `[Extensions]` 段均**无任何扩展条目**       |
| 扩展服务配置    | `ManagerEnabled=true`；`ServerUrl=https://slicer-packages.kitware.com`（`LastServerAPI=Girder_v1`）；`FrontendServerUrl=https://extensions.slicer.org`；`InstallPath=slicer.org/Extensions-34645` | `slicer.org/Slicer-34645.ini`                                                                                     |
| 网络可达性     | **可达**（kitware 有 HTTP 业务响应，非超时/非 DNS 失败）                                                                                                                                                     | `curl -m 30 https://slicer-packages.kitware.com/api/v1/app/...` → HTTP 400 + JSON                                 |
| 历史使用      | 2026-09-28 ~ 2026-10-05 共 **10 次会话**（最近一次 10-05 22:20）                                                                                                                                       | `Slicer.ini` `[LogFiles]` 000–009                                                                                 |
| 曾加载场景     | `NasalSeg_P001_Slicer.mrml`（`P001_img` + `P001_seg`，spacing `0.585938 / 0.585938 / 1.5`）                                                                                                     | `Slicer.ini` `[RecentlyLoadedFiles]` 解码；项目内 `work/NasalSeg_P001_Slicer.mrml` 与 `work/NasalSeg_P001_Slicer场景.mrml` |

### 1.1 对先前表述的诚实修正

段主在 21:08 那轮曾说「T-019 结论卡所记『本机验证软件为 Slicer 5.12.4』**需复核**」。**现复核完毕：该记录属实**——注册表、配置、日志三重证据一致。此前"未找到"是因为当时未查注册表、且 Slicer 已从 `软件\新建文件夹\` 迁到 `软件\slicer\`。

> 附带发现（与本卡无关，供其他卡参考）：项目内存在 `NasalSeg_按患者/P001/`（spacing z=1.5mm）的 Slicer 场景文件，说明 Slicer 曾用于加载 P001 影像+分割。

---

## 2. 扩展可得性（外部核验）

**来源：3D Slicer 官方论坛，SlicerHeart（CHOP, PI M. Jolley）+ SimVascular（Stanford, PI A. Marsden）联合发布帖**  
<https://discourse.slicer.org/t/new-modules-for-generation-cfd-simulation-ready-meshes/48250>

原文明示：

> All these modules are available via the **VMTK and SimVascular extensions** for the latest Slicer Stable Release (**currently Slicer-5.12.4**) and very latest Slicer Preview Release.

→ **与本机版本逐字对上**。模块可串联使用，也可**独立使用**（官方原文："if you already have the clipped surface mesh then you can go straight to the CFD mesh generator module"）。

**来源：SlicerVMTK 扩展官方模块清单**（<https://github.com/vmtk/SlicerExtension-VMTK>），相关模块：

- `Extract Centerline` — 从分割或模型提取血管树中心线，可检测非流形边
- `Clip vessel` — **Clip a segmentation or model normal to the centerline**
- `CFD Mesh Generator` — **Fill a clipped vessel surface with tetrahedra for a CFD solver, using TetGen, fTetWild or Netgen, with capping, surface remeshing and an optional prismatic boundary layer**
- `Branch clipper`、`Cross-Section Analysis`、`Centerline disassembly` 等

**未实测**：本机尚未安装任何扩展；扩展包的下载 URL 与体积未逐字节验证（Girder API 路由未命中，见 §5）。

---

## 3. 能力与本项目管线映射（逐项判定）

### 3.1 `CFD Mesh Generator` — **可独立使用，贴合度最高** ✅

官方能力：从表面网格填充四面体；支持 capping、表面重网格、**可选棱柱边界层**；**三个引擎**：

| 引擎         | 许可                            | 商用                |
| ---------- | ----------------------------- | ----------------- |
| TetGen     | AGPL（"extremely restrictive"） | 多数用途需**付费商业许可**   |
| **NetGen** | **LGPL**（弱 copyleft）          | **免费商用、无需开源自有代码** |
| fTetWild   | MPL2.0                        | 免费商用              |

还有：基于输入表面网格标签的**边界曲面自动标注**；区域各向同性加密（已实现但未在 UI 暴露）。

**与现状对比**：

- 引擎内核与我们的首选**同为 NetGen** → 不引入新内核风险；
- 但它额外提供我们**完全没有**的**棱柱边界层**——这正是 OpenFOAM `snappyHexMesh` 的强项、而当前 Netgen 路线缺失的一环；
- 它还提供**面标签自动传播**，而我们现在靠 `netgen_vol_to_msh.py` 手工指定 descriptor 映射（项目自定方法）；
- 官方明示**不依赖 Clip Vessel** → 可直接吃我们现有 STL。

⚠️ **已知风险**：

- **单位**：Slicer 用 **mm-g-s**；本项目 STL 单位为**米**（项目硬坑，面积判据需传 `unit_scale=1e6`）→ 进出必须显式换算；
- **输出格式未知**：生成的是 mesh-complete / .vtu / .msh 尚未验证；转 OpenFOAM `polyMesh` 的路径**未验证**（可能是工作量最大的一环）；本次未取到扩展包，无法读其源码。

### 3.2 `Clip Vessel` — **有一条对我们不利的硬限制** ⚠️

**官方 README 原文**（ClipVessel 模块，作者 David Molony，已并入 SlicerVMTK）：

> **All branches/vessels should contain a centerline otherwise the clipping may produce undesired geometries in regions without a centerline.**

**作者在论坛对实测反馈的答复**（<https://discourse.slicer.org/t/vmtk-surface-clipping-contribution/30456>）：

- 多条**平行、紧邻**的管道时行为不可预期。测试者原话："the tubes are almost parallel"、"the clipping may be weird and result in unexpected flow extension"；
- 作者承认："vessels running parallel close to each other could be problematic"；
- 无中心线的邻近结构**必须由用户先手工删除**。

**机制**：裁剪平面 = **垂直于中心线**；第一个 fiducial 点被假定为 inlet；可选 capping（直切/平滑）与 flow extension（原出口在延伸段内渐变为圆形截面）。

**对本项目的直接含义**：

- 鼻腔**不是血管树**——它是**单一连通腔体**；
- 左右两个鼻腔即**两条平行通道**，鼻甲再将其分成多条近平行通道；
- **这恰好是该模块已知会失效的几何形态**。

但它仍可能解决 T-011 的具体痛点（裁剪位置/朝向推荐 + 自动封盖 + 标签命名传播），**前提是能提取到可用的气道中心线**——这一点未验证。

### 3.3 `svMultiPhysics`（SimVascular 求解器）— **不建议替换** ❌

- 有限元（PHASTA 血脉），带 ALE 流固耦合、0D/1D 降阶耦合边界（原文：svFSI/svMultiPhysics 为新一代底层求解器）；
- 我们链路上的 **M1/M2 用户裁定（出口四条主判据）+ `cfd_contract.py` 屏值口径 + T-004/T-006 数值标定 + T-008 诊断口径 + T-010 网格缓存签名**，全部是 OpenFOAM 特有概念（`checkMesh` cell determinant、运动学压力 p、`gmshToFoam`）；
- 换求解器 = 这些**已付 CPU 成本拿到的结论全部清零**，而收益（FSI / 生理耦合边界）在当前阶段（稳态、刚性壁、Δp 10–100 Pa 带）**不是刚需**；
- T-019 已定口径边界：**不得因确认软件链路而自动改写 18 Pa 压力裁定**。

---

## 4. 判定汇总

| 环节                                          | 结论       | 依据                                              |
| ------------------------------------------- | -------- | ----------------------------------------------- |
| ④ 求解器替换                                     | **不建议**  | 判据体系不兼容（M1/M2 + cfd_contract 全绑 OpenFOAM）；收益非刚需 |
| ③ 体网格（`CFD Mesh Generator`，NetGen 引擎 + 边界层） | **值得实测** | 可独立吃现有 STL；补上边界层与面标签传播；内核与现选一致                  |
| ② 开口裁剪（`Clip Vessel`）                       | **谨慎**   | 官方硬限制要求全分支有中心线；已知失效模式（平行管）与鼻腔形态重叠               |
| ① 分割（SimVascular ML 分割）                     | **无必要**  | 现有 Slicer 分割链已用；另起一套无收益                         |

---

## 5. 未验证项 / 风险（诚实清单）

1. 本机**未安装任何扩展**，"能否成功安装、装上能否运行"**未实测**；
2. Girder API 路由未命中（`/api/v1/app/5.12/34645/extension` → `HTTP 400 No matching route`）→ **扩展包下载 URL 与体积未确认**。注：这只影响"自动下载"这一细节，Slicer GUI 的 Extension Manager 应可正常使用（`ManagerEnabled=true` 且服务器已配置）；
3. `CFD Mesh Generator` 的**输出网格格式**及其到 OpenFOAM `polyMesh` 的转换路径**未验证**；
4. 单位风险：Slicer mm-g-s vs 本项目 STL 为米；
5. `Clip Vessel` 在鼻腔上的表现**完全未知**，其已知失效模式与鼻腔形态重叠；
6. **项目规矩不变**：任何候选网格仍必须过本地 `checkMesh` 四门禁（watertight / volume_conserved / openings≥10mm² / patch≤2%），**不得绕过 N6**；
7. 本路线**不解决**患者表面自交、错误入口位置等问题（SimVascular 官方 TetGen 文档同样把开面/自交/极小特征列为网格失败原因，已见 `work/07_cfd_pipeline/网格软件实测比较.md:84`）。

---

## 6. 最小试验设计（供裁定，**尚未执行**）

| # | 试验                                                                                                         | 前置      | CPU | 判定标准                                             |
| - | ---------------------------------------------------------------------------------------------------------- | ------- | --- | ------------------------------------------------ |
| 1 | GUI 安装 SlicerVMTK 扩展 → 用**解析圆管 STL**跑 `CFD Mesh Generator`（NetGen 引擎 + 边界层）→ 导出 → 转 OpenFOAM → `checkMesh` | 无       | 极低  | 同一条圆管上能产出**带边界层且 Mesh OK** 的网格 → 该引擎对我们的价值被证实    |
| 2 | 用 p0 现有 surface（sha256 `0cf50df5…`）直接进 `CFD Mesh Generator`（**跳过裁剪**）                                      | 试验 1 通过 | 低   | 与本项目"Netgen + 局部四面体修复"（T-010 口径）比 `checkMesh` 指标 |
| 3 | 对 p0 surface 跑 `Extract Centerline`                                                                        | 无       | 极低  | 能否得到**合理的气道骨架** → 决定 `Clip Vessel` 是否值得一试        |

**建议顺序**：试验 1 →（若通过）试验 2 →（并行）试验 3。试验 1 与 3 不占 CPU 独占车道，可与 T-037 并行。

---

## 7. 复现入口（本次核验的全部命令）

```bash
# 1. 定位安装（注册表）
powershell -Command "Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*' | Where DisplayName -like '*Slicer*' | Format-List DisplayName,DisplayVersion,DisplayIcon,UninstallString"

# 2. 已装扩展（应为空目录）
find "/d/项目/鼻腔建模/软件/slicer/3D Slicer 5.12.4/slicer.org/Extensions-34645" -maxdepth 2

# 3. 扩展服务配置
cat "/d/项目/鼻腔建模/软件/slicer/3D Slicer 5.12.4/slicer.org/Slicer-34645.ini"

# 4. 网络可达性
curl -s -m 30 -o /dev/null -w "%{http_code}\n" "https://slicer-packages.kitware.com/api/v1/app/5.12/34645/extension"
```

---

## 8. 下一步（需用户裁定）

- **A**：授权安装 SlicerVMTK 扩展，跑**试验 1**（最低成本、直接回答"这个网格器值不值"）
- **B**：暂不安装，仅登记本报告为候选
- **C**：把本路线并入 T-019 参考链路复现的讨论（与 SimScale 替代一起裁定）
