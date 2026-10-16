# T-011 Phase A.1 — p0 体网格化内存阻塞：排查记录

日期：2026-10-16　范围：例 0（p0，ISO_Bone 0.35 mm 各向同性底座）扩展域 × maxh 1.0 × S-A 层流
状态：**阻塞（netgen 侧）**，尚未产出网格与流场

## 一句话结论

netgen 无法在本机为 p0 扩展域生成体网格：其 `generate_mesh` 在 45–113 秒内把内存冲过 10 GB 被 OOM 杀死，
且对**所有**已暴露的尺寸 / STL / 优化参数都不敏感；同一脚本、同一参数跑 b15 却在 ~6.0 GB 处平台化并正常完成。

## 证据表

| 配置 | 表面三角 | maxh | grading | 其它 | 峰值 RSS | 结果 |
|---|---|---|---|---|---|---|
| p0 原始 | 438,028 | 1.0 | 0.1 | – | >10.5 GB | OOM (rc=137, 2:52) |
| p0 原始 | 438,028 | 5.0 | 0.1 | – | >10.5 GB | OOM (4:55) |
| p0 降密度 | 160,000 | 1.0 | 0.1 | – | >10.5 GB | OOM (15 min) |
| p0 降密度+盲焊清洗 | 159,706 | 1.0 | 0.1 | – | 停住刷错 | 非流形，终止 |
| p0 降密度+保流形坍缩 | 159,504 | 1.0 | 0.1 | – | >10.5 GB | OOM (1:53) |
| 同上 | 159,504 | 1.0 | **0.5** | – | 10,119 MB | 45 s 触顶杀 |
| 同上 | 159,504 | 1.0 | 0.1 | **minh 0.3** | 10,137 MB | 45 s 触顶杀 |
| 同上 | 159,504 | 1.0 | 0.1 | **--no-closeedge** | 10,020 MB | 60 s 触顶杀 |
| 同上 | 159,504 | 1.0 | 0.1 | **--no-optimize3d** | 9,954 MB | 45 s 触顶杀 |
| **b15 对照** | 175,204 | 1.0 | 0.1 | – | **6,249 MB** | **✅ 2:46 完成，37.4 MB mesh** |

b15 的 RSS 曲线：3,216 → 5,578 → 5,864 → 5,947 → 5,990 → **平台化** → 6,249 → 完成。
p0 的 RSS 曲线：2,846 → 6,961 → 10,119（无平台）→ 杀。
**平台 vs 失控**是两者最本质的区别。

## 已排除的假设（8 项）

1. **maxh**（最大单元尺寸）1.0 与 5.0 内存完全相同。
2. **grading** 0.1 与 0.5 内存相同，0.5 反而更快失控。
3. **minh**（尺寸下限）0.3 —— 已确认进入 `GenerateMesh{'maxh':1.0,'grading':0.1,'minh':0.3}`，仍失控。
4. **三角面数量** 438,028 → 160,000（2.7×）—— 内存无变化。
5. **尖刺三角形 sliver** —— 用保流形短边坍缩把最短边 0.00046 → 0.050 mm、sliver(<0.01 mm) 139 → 0，
   仍失控。
6. **closeedgefac**（窄缝特判）置 None 关闭 —— 仍失控。
7. **minedgelen** —— netgen 直接拒绝该 kwarg（`Not all kwargs ... could be parsed`）。
8. **optimize3d**（3D 优化，文档标注为内存大户）置 '' 跳过 —— 仍失控。

## 表面本身无缺陷

用 `check_orientation.py` 核对 p0 原始表面（438,028 面）：

- 边界边（只用一次）**0** → 封闭
- 非流形边（>2 邻面）**0**
- 反向邻接（同向遍历）**0** → 朝向一致
- 重复有向边 **0**

即：**拓扑完全正常**。b15 同为全 0。所以不是表面坏，是 netgen × 该几何的相互作用。

几何量：体 30,079 mm³（b15 为 21,580 mm³，1.39×）；壁面 20,761 mm²；两盖 80.26 / 80.46 mm²、出口 226.0 mm²
（与开口阶段 `p0.json` 一致）。

## 硬件约束

主机物理内存 **15.71 GB**（排查时空闲仅 2.18 GB）。WSL 现设 11 GB（`.wslconfig`）。
再往上抬会挤爆主机（Windows 只剩 ~2 GB），不可行。

## 可选出路

| 选项 | 内容 | 代价 |
|---|---|---|
| **A（推荐）** | 换 **snappyHexMesh**（本机 `/usr/bin/snappyHexMesh` 可用）：STL + blockMesh 背景网格 + 加密层，六面体主导，内存高效、专为此类复杂 STL 设计 | 需新建算例；网格类型与 b15(netgen 四面体) 不同，比较口径须注明 |
| B | 换更大内存机器跑 netgen | 本机不可行，需外部资源 |
| C | 缩短 p0 域（砍口咽） | 违反扩展域域标准，不作考虑 |
| D | 暂缓 A.1，T-011 标记为「网格工具阻塞」 | 不解决，仅记账 |

## 诊断脚本与日志（均可复跑）

脚本（`outputs/T-011/`）：
- `inspect_stl.py` —— 三角形质量统计（最短/中位边、sliver、长宽比、包围盒）
- `check_orientation.py` —— 封闭性 / 流形性 / 朝向一致性
- `coarsen_surface_uniform.py` —— 网格吸附式降密度（**会破坏流形，仅作反例**）
- `collapse_short_edges.py` —— 保流形短边坍缩（每步重建拓扑，已验证 once=0/over=0）
- `netgen_mem_probe.sh` —— 带 RSS 曲线采样与自动触顶杀的 netgen 探针
- `netgen_patient_mesh_t047_minh.py` —— 加 `--minh / --minedgelen / --no-closeedge / --optimize3d` 的 netgen 副本

日志与产物（WSL `/home/lenovo2/t011_p0/`）：
- 探针日志 `ng_grad05.log / ng_minh03.log / ng_stlfix.log / ng_noclose.log / ng_noopt.log / ng_b15ctl.log`
- 对照产物 `ng_b15ctl.msh`（37,433,987 B，与 `b15_oroext_maxh1.msh` 同尺寸）
- 去毛刺表面 `placed_dec_col.stl`（159,504 面，最短边 0.050 mm，封闭流形）

## 复跑命令（对照）

```
bash outputs/T-011/netgen_mem_probe.sh \
  /home/lenovo2/patient_cfd/t054_b15_oroext/b15_oroext_placed.stl \
  /home/lenovo2/patient_cfd/t054_b15_oroext/b15_oroext_placed.export.json \
  1.0 0.1 12000 b15ctl
```
