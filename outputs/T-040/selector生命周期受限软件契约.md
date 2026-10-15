# T-040 · selector 生命周期受限软件契约（方案 A）

- 任务卡：`tasks/T-040.md`；执行：2026-10-15 段主对话亲自执行，零 CPU 车道。
- 依赖：T-013（因果诊断 VERIFIED）、T-014（修复边界 VERIFIED，逐字给出「建议下一动作 A」）。
- 声明：**不改生产代码**（`partitioned_surface.py` / `auto_opening_pipeline.py` / `connectivity_opened_surface.py` 三件指纹以 T-014 `source_audit.json` 为准）；只用 T-013/T-014 冻结产物与合成控制。**不放行 p0、不恢复 T-011 矩阵、不放宽任何门。**

---

## 0. 一句话结论

**把「静态 selector 在几何变更后过期」这一隐患类别，写成一个可判定的受限软件契约：selector 必须与其实际作用的当前网格顶点集一一对应（C1）；新增交点顶点的归属由其父面语义决定，落在前序 cap 上的必须显式识别而非静默补 False（C2）；裁剪前做跨平面重叠预检并在命中时诚实拒绝（C3）。契约目标 = 生命周期正确 + 诚实失败，不是让 p0 变绿。**

---

## 1. 问题陈述（T-013/T-014 已证）

**软件事实**（`partitioned_surface.py`，指纹见 T-014）：

- `:115-124`：`mask` 由「未被前序平面改写的原始表面」上的连通性算出；对**前序裁剪新增的顶点无条件补 False**。
- `:139`：`inside & any(signed[face] < 0)` 决定受影响三角形；`:142-150` 遇到此前非 wall cap 即拒绝。
- `:169-186`：只保留 `signed >= 0` 的顶点 + 交点；被删面失去的边若邻居面「不含任何 masked 顶点」而被整面保留，则该边**变成边界边**（T 型接缝）。
- `:198-201`：`outside_plane or (outside_roi and mask is None)` → 抛 `SurfaceClipError`；文本只描述「边界跑出切割面或 ROI」。

**病因**（T-011 `a0_clip_root_cause.md`）：p0 的 outlet 删除区边界在穿过「已经切过、且被加盖过」的鼻孔区域时，产生**不在切割面上的边界边**（774 顶点越面 0.35–4.52 mm），其顶点恰是先前开口的加盖三角面顶点 → 命中 `:201`，报出**误导性文本**。

**生命周期本质**（T-013 `mask_scope_results.json`）：p0 的 live 顶点 mask 没变，变化只涉及**此前删除的 dead 顶点和新增交点**。即：**selector 是在一个几何版本上算的，却被用于一个已被前序平面改写过的几何版本** —— 这是「静态 selector 与几何变更生命周期不同」的根因。

---

## 2. 契约目标与非目标

**目标**：
1. 让 selector 的语义在几何变更后可判定——**不存在「在一个几何版本上算、用在另一个几何版本上」的隐式复用**（消除过期隐患类别）；
2. **诚实失败**：当某平面的删除区确实切进前序加盖区时，拒绝理由必须与几何事实一致（「切进前序 cap」），而非「边界跑出切割面」这类误导文本；
3. **零行为变更**：在不发生跨平面几何重叠的场景下，契约实现与现状**逐位一致**（不得静默改动已通过例）。

**非目标**：
- ❌ 不解决 p0 放行（p0 根因 = 鼻孔 landmark 斜 → 几何重叠 + outlet 1090.43 mm² 超带 (120,500)，属**解剖正确性**，T-014 方案 C，需王湧瑞复核）；
- ❌ 不放宽任何门（cap / 拓扑 / 体积 / 面积 / N6）；
- ❌ 不把「报错变清楚」冒充 p0 `auto_pass`。

---

## 3. 顶点生命周期状态机（契约的形式基础）

每次 `clip_and_cap(name, ...)` 后，网格顶点集按下述状态转移：

| 状态 | 定义 | 来源 |
|---|---|---|
| `ORIGINAL_KEPT` | 原始表面顶点，`signed >= 0` | 输入表面 |
| `ORIGINAL_DELETED` | 原始表面顶点，`signed < 0`（被删） | 输入表面 |
| `NEW_INTERSECTION` | 本次裁剪在切割面上新生成的交点顶点 | 本次 `name` |
| `NEW_CAP` | 本次为封闭开孔新生成的加盖三角面顶点 | 本次 `name` |

**lineage 数据结构**（契约要求实现方显式维护，当前生产未保存——T-014 §「已有产物最小复核」已证「不能唯一归因到某 seed/连接桥」即因缺此结构）：

```
vertex_lineage[v] = {
    "state": ORIGINAL_KEPT | ORIGINAL_DELETED | NEW_INTERSECTION | NEW_CAP,
    "origin_plane": <生成该顶点的平面名 | "input">,
    "parent_face_ids": [<该顶点所属原始/前序面的面 id>],   # 用于归属判定
    "inherits_selector": <按 §4 规则解析出的 selector 值 | null>,
}
```

---

## 4. selector 归属规则（契约条款，核心）

**C1 · 离散化一致性（消除过期复用的硬条件）**
> 任何 selector 必须与其**实际作用的当前网格顶点集**一一对应。禁止把在一个几何版本（顶点集）上算出的 selector 数组，直接用于另一个已被前序平面改写的顶点集——二者长度/索引/连通性必须绑定。

- 判定：对每个待裁剪平面，若其 selector 的顶点数/索引 hash ≠ 当前网格顶点集，则该 selector 视为**过期**，不得直接使用（必须按 C2 重新归属，或在检出跨版本复用时显式拒绝）。

**C2 · 新增顶点归属（lineage 决定 selector 值）**
> `NEW_INTERSECTION` / `NEW_CAP` 顶点的 selector 归属，由其 `parent_face_ids` 的语义决定，而非无条件补 False：

| 父面语义 | 归属规则 | 理由 |
|---|---|---|
| 父面 = `ORIGINAL_*` 且属 wall | 按该顶点在**当前网格**上的侧向连通性取值（与既有 flood 语义一致） | 保持不相交场景零差异 |
| 父面 = **前序 `NEW_CAP`** | 显式标记为「跨平面 cap 接触」，**禁止静默补 False**；交由 C3 拒绝或由显式接口裁决 | 静默补 False 正是误导文本的来源 |

> ⚠️ C2 的旧实现（无条件补 False，`partitioned_surface.py:115-124`）在**不相交场景**下与正确归属**等价**（无前序 cap 接触），故可保留 —— 这正是五例零差异的原因；差异只在**跨平面重叠**场景出现。

**C3 · 跨平面重叠预检（诚实失败）**
> 在某平面裁剪前，检查其删除区（按 C2 归属后）是否与**前序 cap 顶点集**相交（`np.isin` 集合查询 / `affected` 面与前序 patch 共享顶点）。命中即抛 `SurfaceClipError`，理由写明「cutting plane intersects an earlier cap」并附 `conflicting_triangles` / `earlier_patch_counts`（T-013 `overlap_control` 已实测此形态）。

---

## 5. 诚实失败定义（验收锚）

| 场景 | 现状行为 | 契约行为 | 依据 |
|---|---|---|---|
| 合成相交（z=2 cap ∩ x=2 plane） | `ValueError`「unexpected boundary outside cutting plane or ROI」（**误导**） | `SurfaceClipError`「cutting plane intersects an earlier cap」+ details（**准确**） | T-013 `overlap_control` 实测（5 冲突三角形，`earlier_patch_counts={bottom:5}`） |
| 合成不相交（z=2 / z=6） | 通过，体积 64 mm³、面积 96 mm²（两 cap 各 16 mm²） | **逐位不变** | T-013 `disjoint_old` / `disjoint_control` 实测 |
| p0 真实例 | `ValueError`「unexpected boundary outside cutting plane or ROI」（误导） | `SurfaceClipError`「outlet 删除区切进 nostril_L/R 加盖区」（准确），**仍拒绝** | T-011 Q4 候选 2/3 实测 + T-013 774 冲突三角形（L 458/R 316、signed −4.52~−0.35 mm、严格跨面=0） |

> **关键**：契约下 p0 的 `passed` 仍为 `false`（诚实失败）；改变的是**拒绝理由的准确性**与**隐患类别的消除**，不是结果。

---

## 6. 回归保证（零行为变更的边界）

**契约只在「删除区与前序 cap 相交」场景改变行为**；其余场景必须与现状逐位一致。

已有实测支撑（引用，不重跑）：
- T-013 `mask_scope_results.json` / T-011 Q4：`b01/b02/b21/b22/b23` 上「每平面在当前网格重算」变体，**掩码 True 计数与最终三 cap 面积逐位相同（差 0.0 mm²）**；
- T-013 `disjoint_control`：不相交合成控制通过，与生产 output 一致（体积 64 / 面积 96，`boundary_edges=0`、`nonmanifold_edges=0`）。

**回归验收要求**（留给实现卡）：五例 `array_sha256`（各自 `*_baseline.json` 内）+ 三 cap 面积逐位断言；未覆盖的 b03–b20/b24 须在实现卡全量回放后再放行。

---

## 7. 与 T-014 三个候选的关系

| T-014 候选 | 本契约关系 |
|---|---|
| **A · 先修 selector 生命周期的可观察契约** | **本卡即 A 的规格化交付**：C1/C2/C3 三条款 + 诚实失败定义 + 回归边界。目标逐字对齐 T-014「生命周期正确和诚实失败」。 |
| B · 限定正确解剖删除区域 | 需要正确 `allowed_delete_region` / `protected_region` / `target_outlet_loop`（T-014 缺失项），解剖依赖，**本卡不涉**。 |
| C · 复核确认后重新定义输入切面 | 需王湧瑞对 CT 三视图确认 intended level/normal/keep side，解剖依赖，**本卡不涉**。 |

**与 T-014 建议的对应**：T-014「Lead 可先立 A 的受限软件契约」→ 本卡立之；「若要进入生产修复，Lead 仍须明确选定接口和回归范围」→ 接口 = C2 的 lineage 归属接口，回归范围 = §6 的五例 + 全量回放条件。

---

## 8. 未确认项（不当作已证）

1. **本卡只出契约规格，未实现、未端到端实测**：C2/C3 的行为断言来自 T-013/T-011 已有实测 + 代码阅读；本卡未新跑真几何。
2. **lineage 数据结构的存储开销未评估**：生产当前未保存 `vertex_lineage`，实现需评估顶点级 provenance 的内存/时间成本。
3. **C1 的「过期检出」判定阈值未定**：顶点数/hash 比对的具体口径（严格相等 vs 容差）需实现卡确定。
4. **未覆盖的病例**：b03–b20、b24 及 p1–p3 未在契约下回放；「全量零差异」未证。
5. **p0 的拒绝理由文本在契约下的**逐字**形式未端到端产出**（引用 T-013 `overlap_control` 的同构形态，非 p0 实跑）。

---

## 9. 交接

- 交付物：本规格 + `outputs/T-040/verify_contract_against_known_answers.py`（只读核对已知答案）+ `verify_contract_against_known_answers.json`。
- 下一步（留待 Lead 裁定）：若要进入生产修复，按 §6 选定接口与回归范围，另立实现卡；实现卡须全量回放 + p0 完整 N6 + 输入/生产双指纹。
- **T-011 维持 OPEN**；p0 解剖修复（B/C）待王湧瑞复核；患者工作台「未准入」身份不变。
