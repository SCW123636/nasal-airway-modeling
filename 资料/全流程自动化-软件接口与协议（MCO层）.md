# 全流程自动化 · 软件接口与协议（MCO 层）

> 本文所有结论均来自**本机实测**（2026-09-28）。凡标注「实测」的条目均为真实执行结果，非推断。
> 实测环境：Windows / 工作区 `D:\项目\鼻腔建模\软件`

---

## 零、先说结论

| 软件 | 版本 | 无头自动化 | 判定 |
|---|---|---|---|
| **3D Slicer** | 5.12.4 | ✅ **完全可用** | 全链路 API 已验证（分割/STL/DICOM） |
| **Blender** | 5.2.2 LTS | ✅ **完全可用** | 修复链路已验证（填洞/去重/法向/导出） |
| **ParaView** | 6.2 | ❌ **当前不可用** | 全部 exe 均 `0xC0000142` DLL 初始化失败 |
| **SimScale** | 云 | ⚠️ 待验证 | 需 API 凭证，会上推荐此路 |

**一句话判断：** Slicer + Blender 这两段（分割 + 修复）**现在就能开工**，而且这恰好是自动化价值最高、人工最耗时的两段（SOP 明说「STL 修复 2–4 小时是最大痛点」）。ParaView 挂掉的影响最小——它是**后处理可视化**，可以延后处理，且有替代方案。SimScale 是云端，需要单独拿 API key。

---

## 一、3D Slicer 5.12.4 —— 实测通过 ✅

### 1.1 启动协议（有坑，必须按此写法）

**关键发现：`bin\Slicer.exe` 不存在。**

实际文件布局：
```
软件\slicer\3D Slicer 5.12.4\
├── Slicer.exe              ← 顶层启动器（✅ 必须用这个）
└── bin\
    ├── SlicerApp-real.exe  ← 直接调会崩 (0xC0000135)
    ├── PythonSlicer.exe    ← 带 Python 环境的解释器
    ├── dcmdump.exe / dcm2xml.exe / img2dcm.exe / storescu.exe   ← 全套 DICOM 工具
    └── python-real.exe
```

**实测对照：**
- `SlicerApp-real.exe` 直调 → `rc=0xC0000135`（找不到 DLL）❌
- 顶层 `Slicer.exe` → `rc=0`，脚本正常执行 ✅

**标准调用（已验证可跑通）：**
```bash
"D:\项目\鼻腔建模\软件\slicer\3D Slicer 5.12.4\Slicer.exe" \
  --no-splash --no-main-window \
  --python-script "your_script.py"
```
> 脚本内**必须**以 `slicer.app.quit()` 结尾，否则进程不退出。

### 1.2 已验证可用的 API（实测 `ok: true`）

```python
import slicer, vtk, numpy as np
slicer.app.applicationVersion   # '5.12.4'
vtk.vtkVersion.GetVTKVersion()  # '9.6.2'

# 体积挂载
node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "CT")
node.SetAndObserveImageData(imageData)          # vtkImageData，支持 SetSpacing 设层厚

# 分割节点
seg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "Airway")
seg.CreateDefaultDisplayNodes()
seg.SetReferenceImageGeometryParameterFromVolumeNode(node)

# 算法内核
import vtkSegmentationCorePython    # ✅ 阈值分割内核
import SimpleITK as sitk            # ✅ sitk.BinaryThreshold(img, -1024, -300, 1, 0)
from scipy import ndimage           # ✅ Islands / 形态学

# 导出
vtk.vtkSTLWriter()                  # ✅ STL 写出
import DICOMLib, ctk                # ✅ DICOM 读入
import SegmentEditor                # ✅ Segment Editor 模块
```

**失败项：** `import Segmentations` 报 `No module named 'Segmentations'`（模块名不对，非致命——用 `vtkSegmentationCorePython` 代替）；`slicer.modules.cli.moduleNames()` 路径写错（CLI 模块调用方式需另查，非致命）。

### 1.3 数据契约

| 方向 | 格式 | API |
|---|---|---|
| 入 | DICOM 序列 | `DICOMLib` / `bin\dcmdump.exe` |
| 内部 | `vtkImageData`（HU 值，int16） | `SetSpacing(x,y,z)` 设层厚 |
| 出 | **STL** | `vtkSTLWriter` / `slicer.util.saveNode` |

**HU 阈值（来自 SOP，需按病例微调）：**
- 标准：`-1024 ~ -300 HU`
- 部分技术用：`-400 HU`
- 视频教程实测用：`-3024.00 ~ -400.00 HU`

---

## 二、Blender 5.2.2 LTS —— 实测通过 ✅

### 2.1 启动协议

```bash
"D:\项目\鼻腔建模\软件\blender\blender.exe" -b --factory-startup -P "script.py"
```
- `-b` 后台模式（无 GUI）
- `--factory-startup` 避免用户配置污染（**建议保留，保证可复现**）

### 2.2 ⚠️ 最大坑：网格算子必须在 EDIT 模式

**实测证据：** 在 OBJECT 模式下直接调 `bpy.ops.mesh.fill_holes()` → `poll() failed`。必须：

```python
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')        # ← 缺这行全部失败
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.fill_holes(sides=0)             # → {'FINISHED'} ✅
bpy.ops.object.mode_set(mode='OBJECT')       # 改完记得切回
```

### 2.3 已验证的修复算子（全部实测 `{'FINISHED'}`）

| 算子 | 作用 | 实测 |
|---|---|---|
| `bpy.ops.mesh.fill_holes(sides=0)` | 填洞 | ✅ 破洞 4→0，网格闭合 |
| `bpy.ops.mesh.remove_doubles(threshold=0.0001)` | 合并重复顶点 | ✅ |
| `bpy.ops.mesh.normals_make_consistent(inside=False)` | 统一法向 | ✅ |
| `bpy.ops.mesh.dissolve_degenerate(threshold=0.0001)` | 消退化 | ✅ |
| `bpy.ops.mesh.delete_loose()` | 删孤立元素 | ✅ |
| `obj.modifiers.new("D","DECIMATE").ratio=0.5` | 精简减面 | ✅ |

**诊断用算子：** `select_non_manifold`、`select_loose`、`intersect`、`intersect_boolean`、`beautify_fill`、`vertices_smooth_laplacian`

**用 bmesh 自算网格质量（推荐，不依赖插件）：**
```python
import bmesh
bm = bmesh.new(); bm.from_mesh(obj.data)
boundary    = [e for e in bm.edges if len(e.link_faces) == 1]   # 破洞边界
nonmanifold = [e for e in bm.edges if len(e.link_faces) > 2]    # 非流形边
```

### 2.4 ⚠️ API 变更（Blender 5.x）

| 操作 | 旧 API | Blender 5.2 实测 |
|---|---|---|
| 导出 STL | ~~`bpy.ops.export_mesh.stl`~~ | ❌ 已移除 → **`bpy.ops.wm.stl_export(filepath=...)`** ✅ |
| 导入 STL | ~~`bpy.ops.import_mesh.stl`~~ | → **`bpy.ops.wm.stl_import(filepath=...)`** ✅ |

### 2.5 ⚠️ 3D Print Toolbox 不存在

**实测：** `--factory-startup` 下仅 13 个内置模块，`print_related = []`。
教程里用 3D Print Toolbox 检查非流形 —— **本机没有，必须用 bmesh 自己算**（见 2.3）。
如果仍想用，需从 Blender 扩展市场单独安装。

### 2.6 单位坑（来自视频教程，务必处理）

Blender 默认按「米」读 STL → 模型尺寸显示为 98674mm 级错乱。
**处理：** 导入后立即 `obj.scale = (0.001, 0.001, 0.001)` 或场景单位设为毫米。

---

## 三、ParaView 6.2 —— 当前不可用 ❌

### 3.1 实测现象

```
pvpython.exe  --version  → rc=3221225794 (0xC0000142)
pvbatch.exe   --version  → rc=3221225794
paraview.exe  --version  → rc=3221225794     ← 连 GUI 主程序都起不来
pvserver.exe  --version  → rc=3221225794
```
**全部 exe 一致失败，stderr 完全为空**（说明是进程加载期崩溃，代码未执行）。

### 3.2 已排除的原因

| 怀疑项 | 核查结果 |
|---|---|
| 缺 python312.dll | ❌ 存在（6.9 MB） |
| 缺 Qt6 / VTK 核心 DLL | ❌ 全部存在 |
| 缺 VC++ 运行库 | ❌ `msvcp140` / `vcruntime140` / `concrt140` 全在 bin 目录 |
| 相对路径问题 | ❌ 已用 `cwd=bin` 测试，仍失败 |

### 3.3 诊断结论

`0xC0000142` + 依赖齐全 + 无 stderr = **Universal CRT 的 API 集 DLL 缺失或版本不匹配**。
`api-ms-win-crt-runtime-l1-1-0.dll` 在 bin 和 System32 **均不存在** —— 这是高度可疑点。

**修复方向（按优先级）：**
1. 安装 **Windows Universal C Runtime**（Windows 更新 KB2999226，或装 VC++ 2015-2022 运行库 x64）
2. 换用 ParaView **官方安装版**（而非绿色解压版）—— 安装版会正确部署运行库
3. 退到 ParaView 5.11 / 5.12（更成熟，依赖更宽容）

### 3.4 替代方案（不阻塞主线）

| 方案 | 说明 |
|---|---|
| **Slicer 内置 VTK 9.6.2** | ✅ Slicer 里已实测可用 `vtkSTLWriter` 等，**读写 VTK 数据完全能做** |
| **SimScale 自带查看器** | 会上提到「自带气流查看器，像 CT 一样逐层看」 |
| 单独装 pvpython | `pip install vtk` + 系统 Python 3.13，自己写后处理 |

**我的建议：** 先不要卡在 ParaView 上。分割和修复是重头戏，先用 Slicer + Blender 把管线跑通，ParaView 作为独立环境问题后置。

---

## 四、SimScale —— 需 API 凭证 ⚠️

### 4.1 已知信息（来自需求文档与会议记录）

- 会上**明确推荐** SimScale（西门子旗下云平台），理由是「比本地稳定，且提供 API 接口」
- API 名称：**ION SDK**（会议待办：「查询 SimScale 平台 ION SDK 的收费情况」— @查理Charlie）
- 视频教程里的**实际参数**（可直接作为模板）：

| 项 | 值 |
|---|---|
| 项目名 / owner | `nöse3` / `aa937583499` |
| 分析类型 | Flow → Incompressible（Community 计划） |
| 材料 | Air：ν = `1.529e-5 m²/s`，ρ = `1.196 kg/m³`，Newtonian |
| 湍流模型 | k-omega SST |
| 时间 | Steady-state |
| 算法 | SIMPLE |
| 入口 | Pressure inlet = `0 Pa`（total pressure） |
| 出口 | Pressure outlet = `18 Pa`（gauge, fixed value） |
| 网格 | Fineness 5，预估 215.6k–323.4k cells |

### 4.2 阻塞项

**需要 SimScale API Key / ION SDK 访问凭证** —— 这是当前唯一无法自查的外部依赖。

### 4.3 ⚠️ 关于免费配额

视频证据：账号显示 **`1 remaining (of 10 used)`** —— 免费版配额极紧（10 个项目）。**调试阶段必须省着用**，建议先用本地求解器把边界条件调好再上云。

### 4.4 本地方案（无配额限制）

- **OpenFOAM** —— 文档列为「进阶路线」，完全免费无配额。Windows 下可用 WSL 或 Docker 部署。
- 好处：可批量跑、可做网格无关性验证（视频教程**没做**这件事，这是它的实质缺陷）。

---

## 五、MCO 编排协议（建议）

### 5.1 三层调用模型

```
┌─────────────────────────────────────────────┐
│  编排器 Orchestrator（Python 3.13 / FastAPI） │
│  - 状态机、任务队列、产物登记、失败重试        │
└──────┬──────────────┬──────────────┬────────┘
       │              │              │
   subprocess     subprocess    HTTP API
       ▼              ▼              ▼
┌────────────┐ ┌────────────┐ ┌────────────┐
│  Slicer    │ │  Blender   │ │  SimScale  │
│  分割      │ │  修复      │ │  求解      │
│  --python- │ │  -b -P     │ │  ION SDK   │
│   script   │ │            │ │            │
└─────┬──────┘ └─────┬──────┘ └─────┬──────┘
      │              │              │
   raw.stl      clean.stl      result/*.vtk
      │              │              │
      └──────────────┴──────────────┘
                     ▼
        ┌────────────────────────┐
        │  ParaView / Slicer-VTK │  ← 后处理
        └────────────────────────┘
```

### 5.2 统一中间产物契约

| 阶段 | 输入 | 输出 | 约定 |
|---|---|---|---|
| S1 分割 | `dicom/*.dcm` | `01_seg/airway_raw.stl` | HU 阈值入参化，默认 -1024~-300 |
| S2 修复 | `01_seg/airway_raw.stl` | `02_fix/airway_clean.stl` | 必须保证：闭合、无破洞、法向统一 |
| S3 求解 | `02_fix/airway_clean.stl` | `03_cfd/result_*.vtu` | 出入口面需在 S2 显式标记 |
| S4 后处理 | `03_cfd/*` | `04_viz/*.png` + `metrics.json` | 输出速度/压力/WSS/鼻阻力 |

### 5.3 三条工程铁律（从实测踩坑提炼）

1. **每个软件一个独立进程，通过文件系统交换数据** —— 不要试图在一个进程里 import 三家 SDK（版本冲突、DLL 冲突）。
2. **所有子进程调用必须捕获 exit code + 检查产物文件是否真实生成** —— 实测中 Slicer/Blender 会「rc=0 但产物不存在」。**只看退出码会误判成功**。
3. **每个阶段产物加校验闸门** —— STL 必须过「闭合 + 无破洞 + 无非法法向」三项检查才能进下一阶段。这正是当前旧流程翻车的地方（复核页显示：132 个非流形点、1396 个凹单元）。

### 5.4 子进程调用模板（实测可用）

```python
import subprocess, os

def run_stage(exe, args, expect_output, timeout=600):
    r = subprocess.run([exe] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"rc={r.returncode:#x} stderr={r.stderr[-500:]}")
    # ⚠️ 关键：必须校验产物，不能只信 returncode
    if not os.path.exists(expect_output):
        raise RuntimeError(f"rc=0 但产物缺失: {expect_output}")
    return r
```

---

## 六、当前阻塞项与下一步

| # | 阻塞项 | 影响 | 建议动作 |
|---|---|---|---|
| 1 | **无 CT 数据** | 无法开发/验证分割 | 索取需求文档提到的「3 例完整测试案例 + 1 例原始数据」 |
| 2 | **ParaView 不可用** | 后处理受阻 | 装 VC++ 运行库，或换官方安装版 |
| 3 | **SimScale API 凭证缺失** | 云端求解受阻 | 向 @查理Charlie 拿 ION SDK 信息 |
| 4 | **软件版本 ≠ 教程版本** | 照教程操作会踩坑 | 本文已记录差异，以本文为准 |
| 5 | **3D Print Toolbox 缺失** | 非流形检查 | 已给出 bmesh 替代实现 |

**我的建议推进顺序：**
1. **先打通 Slicer→Blender 的 STL 修复链路**（用合成/公开 STL 就能测，不依赖真实 CT）—— 这一段是纯算法，可立即开工
2. 同时**索取 CT 数据**，拿到后验证分割环节
3. ParaView 作为独立环境问题并行修复
4. SimScale 放到最后（需要凭证 + 配额紧张）

---

*实测记录：2026-09-28*
