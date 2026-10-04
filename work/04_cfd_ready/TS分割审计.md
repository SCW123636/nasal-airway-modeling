# TotalSegmentator 分割 pipeline 审计报告

审计日期：2026-10-01
审计方式：核对权重文件、TotalSegmentator 运行日志、实际分割产物、质量闸门报告和后处理 manifest。

---

## 1. 脚本链路与实证结论

### 1.1 脚本职责

| 脚本 | 职责 | 实证状态 |
|---|---|---|
| `work/lib/ts_step1_convert.py` | p1/p2/p3 三例 DICOM → NIfTI（SimpleITK，保留 geometry） | ✅ 已跑通，产出见 `C:\ts_work\step1_convert.json` |
| `work/lib/ts_step1_p0.py` | p0（0.35mm ISO）三 part 按 IPP[2] 全局 z 排序拼接 → 单一 NIfTI | ✅ 已跑通，394 层，dz 唯一 0.35 |
| `work/lib/ts_nasal_seg.py` | step1（若缺）+ Task 775 推理 | ✅ p0、p1、p2、p3_t2、p3_t1 均成功 |
| `work/lib/ts_fov_precheck.py` | p1–p3 FOV 三视图预检 PNG（不含 p0） | 产物在 `C:\ts_work\preview` |
| `work/lib/ts_quality_gate.py` | 标签/CT 几何、空气候选体积、HU、连通域、口咽/软腭/硬腭参考及复核图 | ✅ 例0 已运行；结果 `provisional`，不代表人工解剖验收 |
| `work/lib/anatomy_barrier_seg.py` | 从 TS 语义标签生成阈值候选、口咽参考区、开口状态 manifest | ✅ 例0 已运行；鼻窦分支与手工开口面仍待确认 |

### 1.2 实际调用的 task 与输出路径（实证）

来自 `C:\ts_work\p0\ts_run.log` 第一行的原始命令：

```
TotalSegmentator.exe -i C:\ts_work\p0\ct.nii.gz -o C:\ts_work\p0\masks
  -ta head_glands_cavities -d cpu
```

- task：`head_glands_cavities`（包内注册 task_id = 775，权重 `Dataset775_head_glands_cavities_492subj.zip`）
- 专用 task 输出其全部 19 个类别；本机 TotalSegmentator 不允许专用 task 同时传 `--roi_subset`，后处理按文件名选择鼻腔相关标签。
- 输入 DICOM：`资料\脱敏数据_clean\患者{1,2,3}\...`（p1: 512×512×136 @ 0.348×0.348×0.8mm；p0 为 ISO 0.35mm 拼接块）
- 输出设计路径：`C:\ts_work\<p>\masks\<class>.nii.gz`（纯 ASCII 路径，规避 ITK 中文路径写盘 bug）
- 运行环境：`nasal-cfd` venv（Python 3.13，CPU torch）

### 1.3 当前 pipeline 实际状态

1. **Task 775 权重已离线获取并安装**：压缩包为 `C:\ts_work\weights\Dataset775_head_glands_cavities_492subj.zip`，已解压到 TotalSegmentator nnU-Net results 目录；权重约 249 MB。
2. **例0 推理成功**：CPU 运行约 136 秒，日志返回码 0，输出 19 类；鼻腔左右、鼻咽、口咽、软腭、硬腭文件均存在且非空（hypopharynx 等部分类别可为空）。
3. **例0 QC 已执行**：CT/标签 size、spacing、origin、direction 一致；T300 语义空气候选 585,693 voxels / 25.056 mL，HU>0 为 0；原始语义标签含软组织体素，因此必须先与 HU 空气候选相交。口咽空气参考 5.633 mL，与鼻腔候选无体素重叠，但这不能代替裁剪面人工确认。QC 状态为 `provisional`。
4. **例0 后处理候选已生成**：T300 25.056 mL、T350 24.728 mL、T400 24.393 mL；manifest 中鼻窦开口均为 unknown，`G_sinus` 未生成，T300 标为 provisional。
5. p1、p2、p3_t2、p3_t1 也已成功推理并完成 QC。T300 候选分别为 p1 21.538 mL、p2 26.421 mL、p3_t2 32.179 mL、p3_t1 31.455 mL；均无 HU>0 体素，口咽参考区重叠为 0，候选 QC 均为 `provisional`。五个已跑序列的完整数据见 `work/05_ts_seg/QC回测汇总.md`。

---

## 2. `head_glands_cavities` 类表（实证）

来源：本机安装 `nasal-cfd\Lib\site-packages\totalsegmentator\map_to_binary.py:520-538`（不是推测，是包内 class map 原文）：

| label | 类名 | label | 类名 |
|---|---|---|---|
| 1 | eye_left | 11 | **nasopharynx** |
| 2 | eye_right | 12 | oropharynx |
| 3 | eye_lens_left | 13 | hypopharynx |
| 4 | eye_lens_right | 14 | **nasal_cavity_right** |
| 5 | optic_nerve_left | 15 | **nasal_cavity_left** |
| 6 | optic_nerve_right | 16 | auditory_canal_right |
| 7 | parotid_gland_left | 17 | auditory_canal_left |
| 8 | parotid_gland_right | 18 | **soft_palate** |
| 9 | submandibular_gland_right | 19 | **hard_palate** |
| 10 | submandibular_gland_left | | |

加粗为与本项目相关的 5 类。输出为多文件单标签 NIfTI（每类一个 `<class>.nii.gz`），roi_subset 模式下只写选中的类。

**鼻窦补充发现（实证，同文件 `map_to_binary.py:717-725`）**：另一个 task `craniofacial_structures` 提供 `sinus_maxillary`（上颌窦）与 `sinus_frontal`（额窦）。**筛窦、蝶窦在任何 TS task 中均无标签**（全包 grep 确认）。

---

## 3. 与 GPT「6 标签方案」差距矩阵

| # | 目标标签 | TS 是否覆盖 | 覆盖方式 / 缺口 |
|---|---|---|---|
| 1 | 鼻腔主腔 | ✅ 直接覆盖 | `nasal_cavity_left + nasal_cavity_right` 合并即得（已在 roi_subset 中） |
| 2 | 鼻窦（paranasal sinus） | ⚠️ 部分覆盖 | 上颌窦/额窦：需**追加跑第二个 task** `craniofacial_structures`（roi_subset sinus_maxillary/sinus_frontal）。筛窦/蝶窦：TS 全线无标签，只能靠 HU 阈值 + 解剖位置人工分 |
| 3 | 口腔·外部空气 | ❌ 无直接标签 | TS 没有 oral_cavity 标签。但 `hard_palate`(19) + `soft_palate`(18) + `oropharynx`(12) 三类提供了现成解剖裁剪面：硬腭平面以下为口腔侧，可据此从「空气域」中切出口腔/外部空气 |
| 4 | 鼻孔入口 | ❌ 无标签 | 鼻孔开口面须逐例确认；不可仅以鼻腔掩膜最前端自动定入口，后处理支持记录人工确认的 LPS 平面 |
| 5 | 鼻咽出口 | ⚠️ 有鼻咽语义标签 | `nasopharynx` 可作出口定位参考；其下缘不自动等于 CFD 出口面，须避开口咽并逐例确认裁剪面 |
| 6 | 可疑鼻窦开口 | ❌ 无标签 | 需几何推断：鼻腔掩膜与各鼻窦掩膜的接触面（距离变换/膨胀求交）。依赖 #2 先拿到鼻窦掩膜 |

**结论**：6 个目标标签里，TS 直接给 1 个（鼻腔主腔）、可导出 2 个（鼻咽出口、鼻孔入口）、追加 task 可部分补 1 个（鼻窦中的上颌窦+额窦）、纯靠人工/几何 2 个（口腔空气、筛蝶窦、窦口）。

## 4. 鼻腔/口腔分离可行性判断

- `hard_palate`、`soft_palate`、`oropharynx` 是解剖参考标签，不是现成的封闭边界曲面。软腭后缘、鼻咽和口咽交界的出口裁剪面仍须逐例人工确认；不可把“硬腭平面以下”或鼻咽标签下缘直接当作普适屏障。
- 当前处理先将左右鼻腔、鼻咽语义标签与 HU 空气候选相交，以 TS 口咽标签另存口咽空气参考区；检查标签几何一致、鼻腔到鼻咽接触、重叠与体积。QC 为 provisional 时，仍需要 7 点复核和记录鼻孔/鼻咽 LPS 裁剪面。
- TotalSegmentator `craniofacial_structures` 提供上颌窦/额窦候选区域，不代表已经得到正确的鼻窦空气域或自然开口通畅状态。筛窦/蝶窦与所有窦口状态仍须人工判读；阈值连通性不能替代解剖语义。

## 5. 推荐下一步（3 条）

1. 按 7 点清单逐例确认鼻孔、鼻阀、鼻甲间隙、嗅裂、后鼻孔/鼻咽、鼻窦开口和口腔分离，再录入 LPS 裁剪面；在确认前不转正式 CFD 表面。
2. 在统一重采样/配准视图下对照患者3_t1 与 p3_t2 的左右气道和窦口；已跑候选显示总体体积接近，但左右分配差别较大。
3. 需要上颌窦/额窦候选时追加 `craniofacial_structures` task；筛窦/蝶窦仍需人工分割。Task 775 本身不提供鼻窦气腔或开口状态。

---

*附：未能实证项——因权重未下载，暂无真实掩膜可做 label 值统计验证；类表全部来自本机安装包源码，可信度高。*
