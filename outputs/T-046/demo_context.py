# -*- coding: utf-8 -*-
CONTEXT = {
    "title": "三维流线 · 腔内速度与静压",
    "crumb": "鼻腔 CFD 工作台 · 患者流场演示 <b>t004_diag</b>",
    "sub": "WSL /home/lenovo2/patient_cfd/t004_diag · time index 400 · "
           "b15_patient_maxh1_repaired.msh（1,161,194 四面体）",
    "badges": [("warn", "未收敛"), ("", "未临床复核")],
    "honesty_summary": "未达 residualControl 收敛 · 可视化级插值 · 未经人体复核 · 坐标未归位",
    "honesty": [
        "该次跑<b>未达 residualControl 收敛</b>（<code>numerical_validation: unchecked</code>），"
        "Δp 稳态等业务判据尚不成立，此图<b>只能用于看流动形态，不能用于临床结论</b>；",
        "插值为「定位点所在四面体后按重心坐标线性插值」，<b>可视化级</b>，"
        "不等于 OpenFOAM 的定量后处理；定量数字以 postProcessing 的 <code>surfaceFieldValue</code> 为准；",
        "未见人体复核：<code>clinical_status: generalisation_test_only_no_human_review</code>；"
        "几何未过 N6 解剖门，鼻腔内结构归属未经医生复核；",
        "坐标尺为<b>求解器坐标</b>（mm），未做 LPS/解剖方位归位核验 —— "
        "图中 x/y/z 的刻度不等于「左右/前后/上下」，仅用于读数与量纲参照。",
    ],
    "stats": [
        ("抵达鼻咽出口", "36 / 107 条", "占 34%"),
        ("进口面平均静压", "10.29 Pa", "左 8.85 / 右 11.74"),
        ("沿流线速度中位", "1.51 m/s", "0 – 3.232 m/s"),
        ("质量不平衡", "≈1.1e-6", "相对，稳态段"),
    ],
    "facts": [
        ("来源", "WSL <code>t004_diag</code> · time index <code>400</code>（simpleFoam 真实 U/p 场）"),
        ("网格", "<code>b15_patient_maxh1_repaired.msh</code> · 1,161,194 四面体 / 229,033 节点"),
        ("工况", "双鼻孔各 1.25e-4 m³/s（合计 15 L/min，固定 50:50）· 出口 p=0 gauge"),
        ("口径", "T-006/T-041 口径，<b>不可与 T-021/T-029 混用</b>"),
        ("收敛状态", "未达 residualControl（<code>numerical_validation: unchecked</code>）"),
        ("临床状态", "<code>generalisation_test_only_no_human_review</code>"),
    ],
    "footnote": "数据与 T-044 完全一致（同 vtk 重追踪，回归判据 C1）；排版与生成器升级为工作台组件（T-046）。",
}
