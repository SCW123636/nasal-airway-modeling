# NasalSeg 接入阶段

此阶段把公开 NasalSeg 的每位患者 NRRD 转成项目工具可读取的 NIfTI，并保留来源哈希、LPS 几何、体素间距、标签值和转换后哈希。

## 状态契约

原始接入清单中的每个病例初始为 `needs_semantic_mapping`，因为导入器不会自行猜测数值类别。运行论文映射步骤后，当前状态为 `partial_project_mapping`：5 个源结构已有可追溯定义，项目仍缺 `oropharynx`、`hard_palate`、`soft_palate`，因此不能直接进入完整自动定位、几何生成或 CFD。

## 运行

```powershell
$taskPython = 'C:/Users/lenovo/.workbuddy/binaries/python/envs/nasal-cfd/Scripts/python.exe'
& $taskPython -X utf8 'D:/项目/鼻腔建模/work/10_nasalseg_intake/import_nasalseg.py' --patients P001
```

去掉 `--patients P001` 会处理全部患者。批次清单写入 `nasalseg_intake_manifest.json`，每个病例有独立的 `case_manifest.json`、`ct.nii.gz` 和 `masks/nasalseg_labelmap.nii.gz`。

导入后用以下命令做逐例验收：

```powershell
& $taskPython -X utf8 'D:/项目/鼻腔建模/work/10_nasalseg_intake/validate_nasalseg_intake.py'
```

验收报告为 `nasalseg_validation_report.json`，方案桥接状态为 `nasalseg_pipeline_bridge.json`，人工查看清单为 [鼻腔方案桥接清单](鼻腔方案桥接清单.md)。验证器会在 SimpleITK 无法直接读取中文 Windows 路径时使用 ASCII 临时副本；源文件内容和哈希不变。

论文定义的源标签映射可用以下命令生成：

```powershell
& $taskPython -X utf8 'D:/项目/鼻腔建模/work/10_nasalseg_intake/map_nasalseg_labels.py'
```

该步骤按 Scientific Data 论文（DOI `10.1038/s41597-024-04176-1`）生成 `maxillary_sinus_left/right`、`nasal_cavity_left/right` 和 `nasopharynx` 五个二值掩膜，并写入 `nasalseg_semantic_manifest.json`。论文没有 `oropharynx`、`hard_palate`、`soft_palate`，所以这三类必须由额外标注或改用包含这些结构的分割输入；没有它们不能进入当前六类项目定位和 CFD 链路。
