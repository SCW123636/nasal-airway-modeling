# -*- coding: utf-8 -*-
"""schema.py —— 特征 schema v1：口径六元组 + 特征定义 + claim 级别。

每个特征行必须带口径六元组（domain/cut/bc/threshold/numerics/convergence），
否则不许进特征表（B3 分层显式 + B1 数字三件套的工程落地）。

特征分两层：
- Layer G 几何层：不依赖 BC，输入 = 扩展域表面+开口+mask（T-059 批跑产物）
- Layer C CFD 层：依赖 BC，输入 = T-058 已验证 metrics/wss（n=3 切片）

每个特征的 source_layer 标 E0（队列事实）；操作化定义（如 wall 面积
= 表面面积 − 三个帽面积）标 E3，在 definition 里写明，报告里如实带出。
"""

from __future__ import annotations

# ---------------------------------------------------------------- 口径六元组
CONVENTIONS = {
    # T-058 已验证口径（三例全链 + 24 例几何层同源）
    "G": {
        "domain": "extended(nasal_cavity_L+R+nasopharynx+oropharynx)",
        "cut": "anatomical_oblique_perpendicular_to_local_airway_axis",
        "bc": "n/a(geometry_only)",
        "threshold": "HU<-300",
        "numerics": "marching_cubes+cap_bisect(production chain T-058/T-059)",
        "convergence": "n/a(geometry_only)",
    },
    # T-058 三例 CFD 实测口径（metrics JSON 的 boundary_convention 逐字）
    "C": {
        "domain": "extended(nasal_cavity_L+R+nasopharynx+oropharynx)",
        "cut": "anatomical_oblique_perpendicular_to_local_airway_axis",
        "bc": "fixed 50:50 nostril flow split(1.25e-4 m3/s each)+outlet p=0 gauge",
        "threshold": "HU<-300",
        "numerics": "simpleFoam S-A 600 steps, maxh1, mirrors T-006/T-042/T-054",
        "convergence": "false(numerical_validation unchecked, M2 ruling)",
    },
}

# ---------------------------------------------------------------- 特征定义
# layer: G/C；unit；claim: C-a（队列事实，全部如此——常模只报事实）；
# definition 写明操作化定义（E3 假设显式化）；qc_gate: 进常模的准入。
FEATURES = {
    # ---- Layer G：几何（24 例，来源 = opening 报告 + MCA + label 体素）----
    "nostril_area_L_mm2": {
        "layer": "G", "unit": "mm2",
        "definition": "开口阶段 patch 面积（鼻孔帽，cap 目标 80 mm² 二分）",
        "source": "opening_report.patch_areas_mm2.nostril_L",
    },
    "nostril_area_R_mm2": {
        "layer": "G", "unit": "mm2",
        "definition": "开口阶段 patch 面积（鼻孔帽）",
        "source": "opening_report.patch_areas_mm2.nostril_R",
    },
    "outlet_area_mm2": {
        "layer": "G", "unit": "mm2",
        "definition": "口咽工程截断出口面积（FOV 决定，工程属性非解剖；带 [10,600] 病态屏）",
        "source": "opening_report.patch_areas_mm2.oropharynx_truncation_outlet",
    },
    "wall_area_mm2": {
        "layer": "G", "unit": "mm2",
        "definition": "E3 操作化：黏膜面积 ≈ opening 阶段表面面积 − 三帽面积（帽为平面，余量为壁）",
        "source": "opening_report.surface_qc.surface_area_mm2 - sum(patch_areas)",
    },
    "airway_volume_mm3": {
        "layer": "G", "unit": "mm3",
        "definition": "开口阶段封闭表面有符号体积（帽闭合后的域容积）",
        "source": "opening_report.surface_qc.signed_volume_mm3",
    },
    "mca_L_mm2": {
        "layer": "G", "unit": "mm2",
        "definition": "左侧最小截面积（沿 posterior 轴体素计数法，CT 等价 AR 曲线；取 post_entry，入口伪影时以 incl_entry 并列并标 flag）",
        "source": "measure_mca.py per_side.left",
    },
    "mca_R_mm2": {
        "layer": "G", "unit": "mm2",
        "definition": "右侧最小截面积（同左）",
        "source": "measure_mca.py per_side.right",
    },
    "vol_ratio_LR": {
        "layer": "G", "unit": "ratio",
        "definition": "E3 操作化：左/(左+右) 鼻腔容积比，按 TS 语义标签体素计数（不用几何中缝——中缝已被三例交叉验证证伪）；鼻咽/口咽段单列不入比",
        "source": "label voxel counts (nasal_cavity_left/right) x voxel_volume",
    },
    "voxel_z_spacing_mm": {
        "layer": "G", "unit": "mm",
        "definition": "采集元数据：air_mask z 向体素间距（≈层厚；QC 门 ≤0.6 mm 文献红线）",
        "source": "air_mask.nii.gz spacing",
        "qc_gate": "<=0.6",
    },
    # ---- Layer C：CFD（3 例切片，来源 = T-058 metrics/wss）----
    "delta_p_pa": {
        "layer": "C", "unit": "Pa",
        "definition": "双侧入口面积平均压（运动学）×ρ − 出口 0；口径 50:50+斜切",
        "source": "metrics_t058_*_oroext.json",
    },
    "resistance_pa_s_ml": {
        "layer": "C", "unit": "Pa.s/mL",
        "definition": "R = Δp / 总流量（250 mL/s）；全局读数，C5 裁定：不作症状主特征",
        "source": "metrics_t058_*_oroext.json",
    },
    "wss_median_pa": {
        "layer": "C", "unit": "Pa",
        "definition": "全域壁面剪切应力中位（wallShearStress 后处理，|tau|=kinematic×ρ）",
        "source": "wss_t058_*.json",
    },
    "wss_p90_pa": {
        "layer": "C", "unit": "Pa",
        "definition": "全域 WSS 90 分位",
        "source": "wss_t058_*.json",
    },
    "wss_force_n": {
        "layer": "C", "unit": "N",
        "definition": "Σ|tau|·dA 全域壁面剪切力",
        "source": "wss_t058_*.json",
    },
    "mesh_cells": {
        "layer": "C", "unit": "count",
        "definition": "修复后网格单元数（checkMesh 记录）",
        "source": "anat_chain_verification.json / mesh_anat_*.json",
    },
}

REQUIRED_CONVENTION_KEYS = ("domain", "cut", "bc", "threshold", "numerics", "convergence")
