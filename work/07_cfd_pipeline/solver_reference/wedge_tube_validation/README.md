# 生成圆管 wedge 验证证据

本目录保存非患者、5° 轴对称 wedge 圆管的独立结果摘要。它用于确认 OpenFOAM v1912 的 blockMesh 圆弧、wedge 边界、simpleFoam、守恒和后处理链路；不能覆盖或改判原始 STL/snappy 40 mm 失败报告，也不能解锁患者 CFD。

## 已完成案例

| 案例 | 工况 | 结果 | 关键结果 |
|---|---|---|---|
| r21 | 40 mm，80×1×16，developed-flow | fail | 压降误差 2.349%，横向速度末轮残差约 4.4e-4 |
| r22 | 160 mm，320×1×32，relTol 0.01 | fail | 压降误差 1.312%，残差门失败 |
| r23 | 160 mm，320×1×32，relTol 0 | pass | 压降误差 1.312%，流量误差 6.4e-14，质量不平衡 0 |
| r24 | 160 mm，160×1×16，relTol 0 | pass | 压降误差 0.966%，流量误差 6.4e-14，质量不平衡 0 |

`r25` 的 640×1×64 细网格运行已在第 253 步人工停止，只有部分日志，没有写入验证结果，不计入通过或失败。

解析值使用 Hagen–Poiseuille 公式，L=160 mm、D=4 mm、Q=2.5e-4 m³/s、ρ=1.2 kg/m³、μ=1.81e-5 Pa·s；本组 Re≈5276，层流结果只是数值链路对解析解的验证，不是对患者主工况物理流态的判定。

原始 JSON 副本和原始案例路径、SHA-256 位于 `validation_summary.json`。

## 资料依据

- 本机 OpenFOAM v1912 官方示例：`/usr/share/doc/openfoam-examples/examples/incompressible/simpleFoam/pipeCyclic`。该示例用于核对圆弧 blockMesh、旋转周期面和 `bounded Gauss linearUpwind grad(U)` 的词典写法；本项目实际 wedge 结果仍以本机运行日志为准。
- OpenFOAM Foundation 的 `wedgeFvPatchField` 源码：[wedgeFvPatchField.H](https://raw.githubusercontent.com/OpenFOAM/OpenFOAM-11/master/src/finiteVolume/fields/fvPatchFields/constraint/wedge/wedgeFvPatchField.H) 与 [wedgeFvPatchField.C](https://raw.githubusercontent.com/OpenFOAM/OpenFOAM-11/master/src/finiteVolume/fields/fvPatchFields/constraint/wedge/wedgeFvPatchField.C)。源码显示 wedge 是变换型约束面，不能把它等同为普通 symmetry 或任意角向周期面。
- OpenCFD `surfaceFieldValue` 文档：[surfaceFieldValue](https://doc.openfoam.com/2312/tools/post-processing/function-objects/field/surfaceFieldValue/)。本项目用 patch 面通量和面积平均压力做守恒与压降检查。
- Hagen–Poiseuille 目标、Re≈5276 及“层流只是链路验证”的边界在 `work/lib/phantom_validation.py` 和原始 `phantom_validation/validation.json` 中；因此本结果不能直接作为患者主工况的流态选择。
