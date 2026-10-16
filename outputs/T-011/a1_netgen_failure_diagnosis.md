# T-011 A.1 链 step 1（netgen）静默失败 · 诊断笔记

> 记录人：段主对话（Lead）｜时间 2026-10-16 13:2x ｜**只读诊断，未重跑、未改生产链**
> 对象：`outputs/T-011/chain_a1.sh`（mtime 13:18）＋ `outputs/T-011/logs/a1_chain.log`

## 0. 结论一句话

**A.1 锚点格启动后在 step 1（netgen 体网格）静默死亡**：netgen 零输出、未产出 `maxh1.msh`，导致 step 2/3 连锁坍塌、链终止。**最可能是内存（OOM/SIGKILL）**，而 `2>&1 | tail -30` 把"零输出"这一 OOM 特征吞掉了 → 真实证据灭失。**未验证**（重跑取证待授权）。

## 1. 现场（实测）

- `outputs/T-011/logs/a1_chain.log` 稳定 10 行，全文：

```
== step 1: netgen volume mesh (maxh 1.0) ==
== step 2: repair boundary tetrahedra ==
    mesh = meshio.read(source)
  File ".../meshio/_helpers.py", line 71, in read
    return _read_file(Path(filename), file_format)
  File ".../meshio/_helpers.py", line 90, in _read_file
    raise ReadError(f"File {path} not found.")
meshio._exceptions.ReadError: File /home/lenovo2/t011_p0/maxh1.msh not found.
== step 3: scaffold + gmshToFoam ==
cp: cannot stat '/home/lenovo2/t011_p0/maxh1_repaired.msh': No such file or directory
```

- **step 1 整段无任何输出**（既非 traceback，也非成功报告）→ netgen 静默退出。
- WSL 进程表无 netgen / simpleFoam / gmsh 残留 → **链已死，非仍在跑**。
- `/home/lenovo2/t011_p0/` 内容：`placed.stl`、`export.json`、`out/`、`foam_maxh1/{constant,system}` —— **无 `maxh1.msh`、无 `maxh1.arrays.npz`**、netgen 未写任何中间物。

## 2. 输入与依赖（全部在位，排除路径因素）

| 项 | 状态 |
|---|---|
| `/mnt/c/ts_work/t011_p0/stage/placed.stl` | ✅ 127,476,516 B |
| `…/stage/export.json` | ✅ 2,545 B |
| `/home/lenovo2/netgen_venv/bin/python` | ✅ (→ python3) |
| `…/t054_b15_oroext/netgen_patient_mesh_t047.py` | ✅ 11,929 B（**支持 `--maxh`/`--dump-arrays`**，L144/L159） |
| `…/repair_boundary_tetrahedra.py` | ✅ 7,443 B |
| `/home/lenovo2/patient_cfd/b15_maxh1/system`（模板） | ✅ blockMeshDict/controlDict/fvSchemes/fvSolution |
| `/home/lenovo2/t058_chain_anat/patch_wall_type.py` | ✅ 7,341 B |

## 3. 与已验证可用链的对比

T-058 `chain_case_anat.sh:30-31`（**b15/b01/b02 三例跑通、3/3 CHAIN-DONE**）：

```
$VENV "$SCRIPTS/netgen_patient_mesh_t047.py" "$STAGE/placed.stl" "$STAGE/export.json" \
      "$STAGE/maxh1.msh" --maxh 1.0 2>&1 | tail -4
```

T-011 `chain_a1.sh` step 1：

```
$VENV "$SCRIPTS/netgen_patient_mesh_t047.py" "$STAGE/placed.stl" "$STAGE/export.json" \
      "$STAGE/maxh1.msh" --maxh 1.0 --dump-arrays "$STAGE/maxh1.arrays.npz" 2>&1 | tail -30
```

**命令同构**；两处差别：① 多 `--dump-arrays`（脚本 L159 确认受支持，非致因）；② `tail -4`→`tail -30`（只影响可见行数，非致因）。→ **排除调用语法；问题在 p0 几何/资源**。

## 4. 推断（标注「未验证」）

- **主假说 · 内存**：WSL 盒配额 7.8 GB（项目记忆），netgen 单例 RSS 峰值 ~5.8 GB。p0 = A 底座 **0.35 mm 各向同性**（比 b15 患者数据更细，T-011 卡原注释即预警「maxh 1.0 的 cell 数可能高于 b15 的 1.16 M」）→ **cell 数/峰值内存可能超配 → OOM killer SIGKILL**。SIGKILL 不给 Python 任何输出，与"零输出"特征吻合。
- **证据灭失**：`… 2>&1 | tail -30` 管道只保留 stdout/stderr 的**尾部文本**；被 SIGKILL 时无文本可留 → 日志空白。这正是本项目第 7 类事故（"输出合法但与事实不符"）的同类风险：**取证方式本身丢掉了真因**。

## 5. 取证与修复建议（未执行，待授权）

1. **保真重跑 step 1**（不要过管道）：
   `… netgen_patient_mesh_t047.py … --maxh 1.0 > /tmp/a1_netgen.log 2>&1`，直接读 `a1_netgen.log` + `dmesg | tail`（看 OOM kill 记录）。
2. **若确认 OOM**：调**大** `--maxh`（如 1.5 / 2.0）先报 cell 数（T-011 卡原定的"先报成本再定"纪律），或先跑一个只出 cell 数的 dry-run；必要时提高 WSL 内存配额。
3. **若 netgen 拒绝 p0 几何**（非资源）：另立卡查 stl 合法性（自交/退化面）。
4. **纪律**：本卡后续所有 WSL 长步骤统一 `> log 2>&1`（不接 `tail`），保证 SIGKILL/OOM 可取证。

## 6. 边界

- 本笔记为**只读诊断**，未改生产链、未重跑、未动任何既有产物；A.1 状态仍为「未开始/失败」，T-011 卡状态不变。
- 本次未重跑的原因：CPU 独占车道在 13:18–13:2x 有**并行会话**活动（同时刻 `outputs/T-059/run_mca_t059.py` 13:21 在改），按车道规则「同一时刻只能 1 个 CPU 重活」不抢占。
