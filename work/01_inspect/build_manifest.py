# -*- coding: utf-8 -*-
r"""从 affine_summary.json 生成带真实 4x4 仿射的 manifest 参考文件。

输出 work/01_inspect/manifest_reference.json
manifest 字段按外部策略文档(GPT)指定：单位/坐标系/仿射/SeriesUID/阈值/
重采样间距/平滑抽稀/裁剪面/各入口出口与鼻窦开口状态。
"""
import os, json
import numpy as np

ROOT = r"D:\项目\鼻腔建模"
SRC = os.path.join(ROOT, "work/01_inspect/affine_summary.json")
OUT = os.path.join(ROOT, "work/01_inspect/manifest_reference.json")

ROLE = {
    "例0_Bone_0.35mm": "CFD-primary",
    "患者3_t2_0.6x0.6_BONE": "CFD-primary",
    "患者3_t1_1.0x0.5_bone": "eval-longitudinal",
    "患者1_1.0x0.8_Bone": "eval-robustness",
    "患者2_Sinus0.75_H40s": "eval-robustness",
}


def build_affine(sp, org, iop, normal):
    row = np.array(iop[0:3]); col = np.array(iop[3:6]); n = np.array(normal)
    M = np.eye(4)
    M[0, 0:3] = [row[0]*sp[0], col[0]*sp[1], n[0]*sp[2]]
    M[1, 0:3] = [row[1]*sp[0], col[1]*sp[1], n[1]*sp[2]]
    M[2, 0:3] = [row[2]*sp[0], col[2]*sp[1], n[2]*sp[2]]
    M[0, 3], M[1, 3], M[2, 3] = org[0], org[1], org[2]
    return [[round(float(x), 6) for x in row] for row in M]


def main():
    data = json.load(open(SRC, encoding="utf-8"))
    # 阈值三套（外部策略：主 T300，回测 T350/T400）
    thresholds = {
        "T300": -300, "T350": -350, "T400": -400,
        "primary": "T300",
    }
    out = {
        "schema_note": "manifest 字段定义来自外部策略文档(GPT 吸收)，单位固定 mm，坐标系 default LPS",
        "global": {
            "unit": "mm",
            "coordinate_system_default": "LPS",
            "slicer_internal": "RAS (加载时 x,y 取反)",
            "thresholds_HU": thresholds,
            "phi_warning": "本 manifest 几何来自原始 B 块(含 PHI：患者/医生真名+医院地址)。"
                           "对外交付的 CFD 网格/结果必须改用 资料/脱敏数据_clean/ (B') 同源几何。",
        },
        "series": [],
    }
    for d in data:
        if "error" in d:
            continue
        sp = d["itk_spacing_xyz"]; org = d["itk_origin_xyz"]
        raw = d.get("raw", {})
        rec = {
            "label": d["label"],
            "role": ROLE.get(d["label"], "eval"),
            "source_series_uid": d["series_instance_uid"],
            "manufacturer": d.get("manufacturer", ""),
            "institution": d.get("institution", ""),
            "modality": d.get("modality", ""),
            "convolution_kernel": d.get("convolution_kernel", ""),
            "unit": "mm",
            "coordinate_system": "LPS",
            "spacing_xyz": sp,
            "origin_xyz": org,
            "affine_4x4_LPS": build_affine(sp, org, raw.get("iop_first", [1,0,0,0,1,0]),
                                           raw.get("normal_unit", [0,0,1])),
            "ipp_first": raw.get("ipp_first"),
            "iop_first": raw.get("iop_first"),
            "normal_unit": raw.get("normal_unit"),
            "tag_slice_thickness": d["tag_slice_thickness"],
            "dz_verified_by_ipp": raw.get("dz_from_neighbor_ipp"),
            "rescale_intercept": d["rescale_intercept"],
            "hu_range": d["hu_range"],
            "is_isotropic_for_cfd": abs(sp[0]-sp[2]) < 0.05 and abs(sp[1]-sp[2]) < 0.05,
            # ---- 以下为每次 CFD 导出须填写的字段（模板，待填）----
            "cfd_export_fields_to_fill": {
                "resample_spacing_mm": "<填，建议各向同性，如 0.3>",
                "smoothing_mm": "<填实际毫米数，谨慎>",
                "decimation_ratio": "<填，如 0.5>",
                "clip_plane_position": "<解剖裁剪面：后鼻孔/鼻咽，须 ENT 确认>",
                "inlets": [{"name": "nostril_L", "status": "open"},
                           {"name": "nostril_R", "status": "open"}],
                "outlet": {"name": "nasopharynx", "status": "open", "bc": "0 Pa gauge (主)"},
                "sinus_ostia_status": [
                    {"sinus": "<额窦/上颌窦/筛窦/蝶窦>", "status": "open|closed|unknown",
                     "note": "开口状态清单：有意保留 or 误封闭"}
                ],
            },
        }
        out["series"].append(rec)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("[done] ->", OUT)
    for s in out["series"]:
        print(f"  {s['label']:24s} role={s['role']:16s} isoCFD={s['is_isotropic_for_cfd']} "
              f"dz={s['dz_verified_by_ipp']} (tag={s['tag_slice_thickness']})")


if __name__ == "__main__":
    main()
