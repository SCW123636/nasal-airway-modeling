# T-011 A.0 根因取证：`nasopharynx_outlet: unexpected boundary outside cutting plane or ROI`

- 取证时间：2026-10-15 15:39–15:56（零 CPU 车道：只读代码 + 单进程小探针，未建网格、未求解）
- 取证对象：`p0`（`C:\ts_work\batch27_surfaces\p0\source_surface.vtp`，landmarks `work/06_auto_landmarks/p0/landmarks.json`，sha `468fa632…`）
- 硬约束遵守：`work/lib/` 下**未改任何文件**（`partitioned_surface.py` mtime 2026-10-11 19:17:29 / `auto_opening_pipeline.py` 2026-10-13 17:48:31 / `diag_p0_naso_clip.py` 2026-10-15 10:15:51，均早于本次会话；未 `git add`/`git commit`）；全部产物写在 `outputs/T-011/`

---

## 一句话结论

**结论：不是「该开口没拿到 mask」——`mask` 一直都在（`is None` 为假）。真因是 `outside_plane=True`。**

`nasopharynx_outlet` 的裁剪边界里混进了 774 个「前两个鼻孔平面切出来的顶点」，它们坐在切割面**被删除侧 0.35–4.52 mm 处**，边界因此不共面（切成 10 个环）；第 195 行的 `outside_plane` 命中，第 201 行抛错。这 774 个顶点全部由先处理的 `nostril_L`(456) + `nostril_R`(318) 产生，且它们「保留侧」的邻居面 **100% 是两个鼻孔的加盖三角面**——即 outlet 的删除区切进了先前开孔的加盖区。

---

## 取证方法与命令原文

两个新探针（只读，不改生产代码；`clip_and_cap` 只在运行时被 monkeypatch 成 spy，文件未动）：

```powershell
cd "D:\项目\鼻腔建模"
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python310\python.exe" -u "D:\项目\鼻腔建模\outputs\T-011\a0_clip_root_cause_probe.py"
& "C:\Users\lenovo\AppData\Local\Programs\Python\Python310\python.exe" -u "D:\项目\鼻腔建模\outputs\T-011\a0_stale_mask_crosscheck.py"
```

`a0_clip_root_cause_probe.py` 做三件事：
1. 复刻 `clip_areas`（`auto_opening_pipeline.py:124`）的 selectors 构造，逐开口记录 `flood_mask(...)[0]` 的类型/None/dtype/len/True 计数；
2. monkeypatch `auto_opening_pipeline.clip_and_cap` 后跑**真·生产 `process()`**，记录每一次 `clip_and_cap` 收到的 `selectors`，并抓抛错栈帧；
3. 逐行复刻 `clip_and_cap`（含第 202 行加盖、第 205-210 行拓扑/体积校验）并插桩，跑 8 组对照（生产顺序 / 单开口 / 两两组合 / 纯 ROI 盒 / 逐平面重算掩码）。

环境自证（原始输出，`_probe_stdout.txt` 前 3 行）：`198262 verts / 396524 tris  boundary_edges=0  signed_volume=25041.250`；真·生产 `process()` 复跑得到与 10-15 记录**逐字相同**的失败文本：
`process escalations = [{'opening': None, 'reason': 'clip_failed', 'detail': 'nasopharynx_outlet: unexpected boundary outside cutting plane or ROI'}]` → 数据与环境与 10-15 一致。

---

## Q1：生产路径里 `nasopharynx_outlet` 的 `mask is None` 是否为真？

### 判定：**否（mask 不是 None）** —— 置信度：高（直接实测 + 抛错栈帧）

证据 A（真·生产 `process()` 跑一次，spy 记录 5 次真实 `clip_and_cap` 调用；原文见 `_probe_stdout.txt`，`[1]`-`[3]` 为节省篇幅省略，已用脚本核对 5 次的 `raised_msg` 与栈帧**逐字相同**）：

```
clip_and_cap 调用次数 = 5
  [0] auto_opening_pipeline.py:126 clip_areas  selectors_is_none=False keys=['nostril_L', 'nostril_R', 'nasopharynx_outlet']  outlet_mask={'key_present': True, 'mask_is_none': False, 'dtype': 'bool', 'len': 198262, 'true_count': 17922}  raised=ValueError
  [1] auto_opening_pipeline.py:126 clip_areas  ...  raised=ValueError
  [2] auto_opening_pipeline.py:126 clip_areas  ...  raised=ValueError
  [3] auto_opening_pipeline.py:126 clip_areas  ...  raised=ValueError
  [4] auto_opening_pipeline.py:426 process      selectors_is_none=False keys=[...] outlet_mask={'key_present': True, 'mask_is_none': False, 'dtype': 'bool', 'len': 198262, 'true_count': 17922}  raised=ValueError
  抛出点帧: {'file': 'partitioned_surface.py', 'line': 201, 'func': 'clip_and_cap'}
```

- 5 次调用**全部**带着三个键、`nasopharynx_outlet` 的掩码是 `dtype=bool / len=198262 / True=17922` 的 ndarray，没有一次是 `None`；
- 抛错栈帧直指 `partitioned_surface.py:201`，即第 198-201 行那条 `if`。

证据 B（为什么必然如此，`mask is None` 在这个调用路径上不可达）：
- `clip_areas`（`auto_opening_pipeline.py:121-136`）的第 124 行 `sel = {k: flood_mask(...)[0] for k in OPENINGS}`，而 `flood_mask`（`connectivity_opened_surface.py:101-164`）**只返回 `(chosen, note)`**，`chosen` 是 ndarray（第 151 行），要么返回数组、要么在第 136/142 行抛错；**从不返回 None**；
- 抛错会被 `clip_areas` 的 `except ValueError`（第 127 行）吞掉，返回 `(None, 原因)`，报错文本就会变成 `no negative-side seed inside the reviewed ROI` 之类；
- 第 426 行的最终裁剪前面有第 421 行 `if len(selectors) != len(OPENINGS): 升级返回` 的守门；本次产物 `C:\ts_work\batch27_opening\p0.json` 的 `selection_notes` 三个开口**齐全**（seed 899/857/1452，selected_faces 2021/1871/37231），说明这道门是通过后才到第 426 行的；
- `partitioned_surface.py:85` `selectors = selectors or {}` 对非空 dict 恒等，第 115 行 `mask = selectors.get(name)` 拿到的是数组。

因此第 198 行 `outside_plane or (outside_roi and mask is None)` 里**只有 `outside_plane` 能成立**。实测：`outside_plane=True`、`outside_roi=True`、`mask_is_none=False`。

> 附带修正上一任探针的第二个缺陷：`diag_p0_naso_clip.py:244` 把 `mask_is_none` 写死为 `False` **恰好与生产一致**，所以那个写死值本身没导致错判；它的错判来自别处——它只对**单个开口单独跑在原始表面上**（`main()` 只调用 `probe()`），文件里为「顺序耦合」写好的 `replay_all()`（第 154-254 行）**从未被 `main()` 调用**。单独跑 outlet 时结论确实是不报错（见下方对照表），但那不是生产跑的形态。

---

## Q2：ROI 盒 vs 裁剪后边界实际范围（出盒多少毫米、哪个方向）

失败平面 `nasopharynx_outlet`（`n_pts_in=199036`，本平面新增交点顶点 2718 个）：

| 项 | x | y | z |
|---|---|---|---|
| ROI `min` (LPS mm) | −23.676 | −168.306 | −669.215 |
| ROI `max` (LPS mm) | 0.951 | −147.525 | −664.165 |
| 裁剪后边界 `min` | −36.884 | −239.549 | −670.714 |
| 裁剪后边界 `max` | −0.209 | −150.203 | −666.024 |
| **出盒（低侧）mm** | **13.208** | **71.243** | **1.499** |
| 出盒（高侧）mm | 0.000 | 0.000 | 0.000 |

- 出盒方向：三个轴都在**下界外侧**；量级最大的是 **y 方向 71.24 mm**（边界一直伸到 y=−239.5，而盒子下界只有 −168.3），x 方向 13.21 mm，z 方向 1.50 mm。
- 但 `outside_roi=True` **不是**本次的触发条件（`mask` 非 None，第 198 行的 `and mask is None` 短路）。真正触发的是共面性：

| 项 | 值 |
|---|---|
| `outside_plane` | **True** |
| 边界顶点离面**最大**绝对偏差 | **4.5218 mm**（容差 `1e-7` mm） |
| 出面顶点数 / 出面边界边数 | **774 / 774** |
| 出面顶点的带符号距离 | −4.5218 … −0.3509 mm（**774 个全在 keep_positive 的负侧，即被删除侧**） |
| 裁剪后边界边 3492 条 / 环 10 个（对照：单开口时 2718 条 / 4 环） | — |

出面顶点与其来源（集合级统计）：

| 项 | 值 |
|---|---|
| 来自原始表面的顶点 | **0** |
| **由前面两个平面新增的交点顶点** | **774（=456[nostril_L] + 318[nostril_R]）** |
| 由本平面自己新增的交点顶点 | 0 |
| 出面顶点「保留侧邻居」的面 patch 统计 | `{'nostril_L': 1374, 'nostril_R': 948}`（**全部是先前开孔的加盖三角面**） |

最坏的 10 个出面顶点样例（原始输出）：

```
{'vertex_index': 198276, 'is_appended_intersection_vertex': True, 'signed_mm': -4.521841993711903,
 'coord_lps_mm': [-11.711, -229.7604, -670.714], 'faces_before_containing': 3,
 'of_those_affected': 2, 'of_those_kept': 1, 'kept_faces_that_are_earlier_caps': 1,
 'mask_true_at_vertex': False}
{'vertex_index': 198275, ... 'signed_mm': -4.50899292373914, ... 'of_those_kept': 3,
 'kept_faces_that_are_earlier_caps': 3, ...}
```

交叉验证（几何自洽）：该顶点 `coord_lps_mm = [-11.711, -229.7604, -670.714]` 同时满足两个平面方程——代入 `nostril_L` 平面（point `[-14.239,-234.666,-668.781]`，normal `[0.0525,0.3425,0.938]`）得 −0.0003 mm（在面上）；对 `nasopharynx_outlet` 平面（point `[-11.516,-158.332,-666.217]`，normal `[-0.0171,0.0004,0.9999]`）得 −4.52 mm（在删除侧）。且它的 z=−670.714 与探针独立测到的 `nostril_L` 裁剪边界 `bd_min z = -670.714` **逐位相同**。

---

## Q3：为什么边界会跑出切割面（逐行定位，只做定位）

### 触发链（文件:行号 → 分支条件 → 实测值）

| 步骤 | 位置 | 分支/条件 | p0 实测 |
|---|---|---|---|
| 1 | `auto_opening_pipeline.py:124` | `sel = {k: flood_mask(points, faces, placed[k], seed_mode='roi')[0] for k in OPENINGS}`——**掩码只在「原始表面」上算一次** | outlet 掩码 len=198262, True=17922（`negative_components_reached=3`） |
| 2 | `partitioned_surface.py:99` | `for name, spec in planes.items()`：顺序 = `OPENINGS` = `nostril_L → nostril_R → nasopharynx_outlet`（`build_placed` 第 139-140 行按 `OPENINGS` 建 dict） | 鼻孔 L/R 先切、先加盖 |
| 3 | `partitioned_surface.py:120-123` | `if len(mask) < len(points): mask = concat(mask, zeros(...))`——**前序平面新增的交点顶点一律补 False** | outlet 迭代时 `len(points)=199036`，掩码只有 198262 → 774 个新顶点被判「不在选区内」 |
| 4 | `partitioned_surface.py:124,139` | `inside = np.any(mask[faces],axis=1)`；`affected = inside & np.any(signed[faces]<0,axis=1)` | affected=34493，其中 31775 个重写后不产生三角形（整面删除） |
| 5 | `partitioned_surface.py:169-186` | 只保留 `signed>=0` 的顶点 + 交点；被删面所失去的边，若邻居面「不含任何 masked 顶点」而被整面保留，则该边**变成边界边**（T 型接缝） | 出面边界边 774 条，两端都是步骤 3 里被补 False 的鼻孔交点顶点（`mask_true_at_vertex=False`） |
| 6 | `partitioned_surface.py:192-195` | `topology` → `edges=boundary_edges`；`outside_plane = max(abs((points[used]-origin)@normal)) > tolerance_mm` | 4.5218 mm > 1e-7 → **True** |
| 7 | `partitioned_surface.py:198-201` | `if outside_plane or (outside_roi and mask is None): raise ValueError(...)` | `outside_plane=True` 命中 → 抛出唯一报错文本 |

**根因一句话**：`mask` 不缺，但它是在**未被前序平面改写的原始表面**上算出的连通性选区；前两个鼻孔平面新增的 774 个交点顶点被第 120-123 行无条件补成 False，于是 outlet 的删除区边界在「已经切过、且被加盖过」的鼻孔区域穿过时，产生了**不在切割面上的边界边**——这些边的顶点恰好是先前开孔的加盖三角面顶点，出切割面 0.35–4.52 mm。

### 对照实验（同一批输入，只改调用形态；`a0_clip_root_cause.json → replica_replay`）

| 实验 | 顺序 | 是否重算掩码 | 结果 |
|---|---|---|---|
| `outlet_alone_with_mask` | 只 outlet，原始表面 | 否 | **不报错**（bd_verts=2718/4 环，偏差 5.68e-14，`outside_plane=False`，`outside_roi=True` 被掩码豁免）；outlet patch 面积 **1090.43 mm²** |
| `nostril_L_then_outlet_with_masks` | L→outlet | 否 | **报错**，偏差 4.5218 mm，出面顶点 456 |
| `nostril_R_then_outlet_with_masks` | R→outlet | 否 | **报错**，偏差 4.0662 mm，出面顶点 318 |
| `production_order_all_three_with_masks` | L→R→outlet（**生产顺序**） | 否 | **报错**，偏差 4.5218 mm，出面顶点 **774**、环 10 —— 文本与生产逐字一致 |
| `production_order_recompute_mask_on_current_mesh` | L→R→outlet | **是**（诊断变体） | 仍失败，但换成 `SurfaceClipError: nasopharynx_outlet: cutting plane intersects an earlier cap`（命中 `partitioned_surface.py:142-151`） |
| `production_order_pure_roi_box_no_selector` | L→R→outlet，`selectors={}` | 纯 ROI 盒语义 | outlet 处 `SurfaceClipError: deleted wall crosses the configured ROI boundary`（113 个冲突三角形，命中第 130-138 行） |
| `outlet_alone_pure_roi_box_no_selector` | 只 outlet，`selectors={}` | 纯 ROI 盒 | 同上，113 个冲突三角形 |

**三条硬结论**：
1. **单开口跑不会报错，生产顺序跑才报错** → 这是跨平面的**顺序耦合**，不是 outlet 平面自身的共面性问题；上一任探针漏掉的正是这一点（`replay_all` 写了没跑）。
2. **「掩码过期」不是唯一病因**：把掩码改成「每个平面在自己当前网格上重算」后 p0 **依然过不去**，只是报错换成「切割面与前序加盖相交」。说明底层条件是**几何重叠**：p0 的两个鼻孔切割平面是斜的（`nostril_L` normal `[0.0525,0.3425,0.938]`），其切割截面在 z 上一直伸到 −670.714，而 outlet 平面在 z≈−666.2 —— 鼻孔的裁剪/加盖区**物理上压在 outlet 的删除区里**。
3. 纯 ROI 盒语义（2026-10-13 之前的路径）在 p0 的 outlet 上**也会失败**，只是更早、换一条报错（`deleted wall crosses the configured ROI boundary`，113 个 straddle 三角形）。即 p0 的 outlet 从来就不是「换一种掩码语义就能裁」的情形。

### 附带发现（对下一步很重要）

单开口复刻得到的 outlet cap 面积 = **1090.43 mm²**，而 `AREA_BAND_MM2['nasopharynx_outlet'] = (120.0, 500.0)`（`auto_opening_pipeline.py:70`）。也就是说：**即便只放宽第 198 行的判据让裁剪通过，p0 的 outlet 仍会在面积门上失败**（第 452-455 行 `gate_failed`），且因为 1090.43 ≥ 目标 250，第 222-223 行会判定「已达标」而不做任何二分位移。
（此项为「实测面积 + 代码推演」，未端到端施加修法实测，见未确认项。）

---

## Q4：可选修法（只给建议，**未实施任何一条**）

前置硬教训（`auto_opening_pipeline.py:240-246`）：曾有一个「修法」把失败探针的区间处理从 `hi=mid` 改成 `continue`，结果静默改动了 b02/b16/b21/b22 四个原本通过的例（outlet cap 268.51→177.44 / 259.71→50.98 / 267.48→120.25 / 250.01→219.02）。下面每条都标出「对已通过例的影响」，并在末列注明是「实测」还是「推断」。

| # | 改哪里 | 代价 | 风险 | 对已通过例的影响 | 依据 |
|---|---|---|---|---|---|
| 1（推荐先做，零行为变更） | 只改报错可读性：`partitioned_surface.py:198-201` 抛错时把 `outside_plane / outside_roi / mask_is_none / 出面顶点数 / 出面顶点是否来自前序平面` 写进消息（或 `details`），并把「边界顶点全部由前序平面产生」单列一个专用错误类型 | 极小：1 处 `raise`，不改任何通过/不通过判据 | 极低 | **零影响（判定逻辑未变）** | 实测：本次 5 次调用全在同一行抛错，而该文本只描述「边界跑出切割面或 ROI」，不含「切进了前序加盖区」这一真因；前一轮误判的主因是没跑顺序重放（Q1 末尾），文本误导是次要因素 |
| 2 | 在 `clip_and_cap` 循环内**做跨平面重叠预检**：对 `mask is not None` 分支，在 `partitioned_surface.py:139` 之后、第 142 行同处，检查「`affected` 面是否与先前 patch 相邻（共享顶点）」或「边界顶点是否落在已有 cap 的点集里」，命中即抛带细节的 `SurfaceClipError`（把当前的「不共面」误报换成「outlet 删除区切进 nostril_L/R 加盖区」的真话） | 小：约 10 行判定 + 一个集合查询（`np.isin`） | 中低：会改变**报错类型与文本**，下游若有按文本分支的地方需同步（本项目 `clip_areas` 只做 `str(exc)` 透传，不解析） | **实测：对 b01/b02/b21/b22/b23 零差异**（这 5 例三种平面各自的出面顶点数=0，不会命中新预检）；其余 19 例未测 | 实测（5 例）+ 代码阅读 |
| 3 | 掩码改为**每个平面在自己当前网格上重算**（`auto_opening_pipeline.py:124` 的「算一次」改成在 `partitioned_surface` 循环内按平面调用 `flood_mask`） | 中：`clip_and_cap` 需要拿到 `seed_mode`/ROI 规格并回调 `flood_mask`，跨模块耦合 + 每例多 3 次连通分量计算 | 中：语义一变，**所有例的第 2/3 个平面的选区都会变**（p0 上直接触发「切割面与前序加盖相交」） | **实测：b01/b02/b21/b22/b23 上掩码 True 计数与最终三个 cap 面积逐位相同（差 0.0 mm²）**；这是本批唯一被实测过的修法，但仍未覆盖全部 21 例，且 p0 不过 → 不能单独作为 p0 的解法 | 实测（5 例 + p0） |
| 4 | 改**输入**而非代码：给 p0 的 `nasopharynx_outlet` 换一个能裁的 reviewed 平面（人工复核一个点），或让 `solve_placement` 在「起始位就 clip 失败」时不要直接放弃（当前 `auto_opening_pipeline.py:216-221` 是 `continue`，导致 p0 从未进入二分：`entered_bisection=false`、`verified_by_clip=null`） | 中：前者=一次人工复核；后者=改搜索策略（改 `solve_placement`），且要重新回放 24 例 | 前者低（只动 p0 一个输入，几何正确性需复核）；后者**高**——正是第 240-246 行那类改动能静默改动已通过例的地方；另外实测 outlet 单开口面积 1090.43 mm² 远超 500 上限，说明「只让它能裁」不够，平面本身也该往鼻腔深处走 | 前者：**只影响 p0**；后者：未测，按历史教训必须先跑 `ab_*_cohort` 全量回放 | 实测（面积、未进二分）+ 代码阅读 |

**不建议的方向**（写出来是为了别被当成选项）：单纯把第 198 行的 `outside_plane` 判据放宽/加容差。实测偏差是 **4.52 mm**，不是 1e-6 量级的舍入（前一任探针在单开口下测到的 5.68e-14 只说明「未被打乱时的共面性」）；放宽只会把 p0 推向 `gate_failed`（1090.43 mm² > 500）或让加盖在非共面环上产生错误几何，属于「把报错藏起来」。

---

## 未确认项（明确列出，不要当成已证）

1. **其余 19 个 auto_pass 例未测**：Q3/Q4 的「是否影响 21 例」只在 b01/b02/b21/b22/b23 五例上实测（掩码重算变体零差异）；b03–b20、b24 未跑。
2. **修法 2、4-后半 只是代码阅读 + 推断，未实现、未端到端实测**；「放宽第 198 行 → 转成 gate_failed」也是由实测面积 1090.43 mm² + 第 222-223/452-455 行推演，未真跑。
3. **微观面级证据未逐面导出**：出面顶点的「受影响邻居是 wall 面、保留邻居是前序 cap 面」来自聚合统计（`of_those_affected` / `kept_faces_that_are_earlier_caps` / `offplane_vert_kept_face_patch_counts`），未把 774 条边的具体面索引逐条列出。
4. **p0 鼻孔平面为什么这么斜、斜得对不对**未评估——这属于 landmark 复核（解剖正确性）范围，本次只做几何因果，不判定 p0 的 landmarks 是否该改。
5. **B 例对照的输入精度**：`a0_stale_mask_crosscheck.py` 用的是报告里 2 位小数的 `offset_from_reviewed_mm`，所以 A 组面积与 10-13 记录有 0.00–1.06 mm² 偏差（b21/b22/b23 的 outlet 逐位一致，b01 outlet 252.79 vs 记录 251.73）；因此「B−A=0.0」这个结论是可靠的（两组用同一 `placed`），但 A 与历史记录的绝对一致性只到 0.1 mm² 量级。
6. **未做 offset 扫描**：没有测「outlet 平面往哪个方向移多少 mm 才能既不切到鼻孔加盖区又在 120–500 mm² 带内」——这需要跑求解/扫描，超出本次零 CPU 车道。

---

## 产物清单（全部在新目录 `outputs/T-011/` 下，生产代码零改动）

| 文件 | 内容 |
|---|---|
| `outputs/T-011/a0_clip_root_cause.md` | 本报告 |
| `outputs/T-011/a0_clip_root_cause.json` | p0 原始实测数据：真·生产 process() 复跑记录、5 次 clip_and_cap 的 selectors 快照与抛错栈帧、复刻重放的 8 组对照逐平面明细 |
| `outputs/T-011/a0_clip_root_cause_probe.py` | p0 探针脚本（可复跑；`clip_and_cap` 仅在运行时被 spy 包装） |
| `outputs/T-011/_probe_stdout.txt` | 上述脚本的完整控制台原始输出（UTF-8） |
| `outputs/T-011/a0_stale_mask_crosscheck.json` | b01/b02/b21/b22/b23 的 A/B 两语义对照（含与 10-13 记录面积的比对） |
| `outputs/T-011/a0_stale_mask_crosscheck.py` | 上述 b 例对照脚本 |

（`a0_p0_clip_diagnosis.json`、`a0_p0_run.json`、`批次记录.md`、`logs/` 为上一任产物，未改动。）
