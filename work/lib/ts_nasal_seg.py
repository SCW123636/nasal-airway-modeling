# -*- coding: utf-8 -*-
"""
S2.3 落地：用 TotalSegmentator 做「解剖先验驱动」的鼻腔分割

为什么选这条路（S2.2 已证伪纯几何路线）：
  TotalSegmentator 的 head_glands_cavities 预训练任务直接输出
    nasal_cavity_left / nasal_cavity_right / nasopharynx
  模型学到的就是「解剖语义」，正是 MEMORY.md 判定必须走的路线。

流程：
  1. DICOM 序列 → NIfTI（SimpleITK，完整保留 geometry：spacing/origin/direction）
  2. TotalSegmentator 只跑鼻腔相关的三个类（省时省显存）
  3. 读回掩膜，与 CT 网格对齐（同 geometry，无需配准）
  4. 输出报告 JSON（供后续闸门检查）

用法：
  python ts_nasal_seg.py p3              # 跑患者3（最佳数据）
  python ts_nasal_seg.py p1 p2 p3        # 批量
  python ts_nasal_seg.py p3 --device cpu # 强制 CPU
"""
import os
import sys
import json
import time
import subprocess

VENV = r"C:\Users\lenovo\.workbuddy\binaries\python\envs\nasal-cfd"
TS_EXE = os.path.join(VENV, "Scripts", "TotalSegmentator.exe")
HF_MIRROR = "https://hf-mirror.com"

# 环境由来（2026-09-30 修正）：
#   nasal-gpu（Python 3.14 + --system-site-packages 复用现成 GPU torch）路线已废弃：
#   3.14 无 cp314 wheel，pip 退化为源码编译，28 分钟零进展。
#   改用 nasal-cfd（Python 3.13.14，官方源 CPU torch），先跑通链路，GPU 后续优化。
#   默认 device 因此改为 cpu。

ROOT = r"D:\项目\鼻腔建模"
WORK = os.path.join(ROOT, "work")
# ★ 坑：ITK/NIfTI 读写不支持非 ASCII 路径（实测报 "nifti library failed to write image"）。
#   所以中间产物一律走纯 ASCII 目录，处理完再用 shutil 拷回项目目录。
OUTBASE = r"C:\ts_work"

# 四例最佳序列 + 患者3_t1 纵向评估序列；p0 由 ts_step1_p0.py 单独转换三 part 拼接。
# p0 的 dcm_dir 留空：它的 NIfTI 由 ts_step1_p0.py 预先生成（三 part 拼 + z 全局排序），
# main 里检测 ct.nii.gz 已存在则跳过 step1。
PATIENTS = {
    "p0": None,
    "p1": os.path.join(ROOT, r"资料\脱敏数据_clean\患者1\______-______\20260127\202-1.0 x 0.8 Bone"),
    "p2": os.path.join(ROOT, r"资料\脱敏数据_clean\患者2\p01360058-____\20250902-Head^07_Sinus (Adult)\4-Sinus  0.75  H40s"),
    "p3": os.path.join(ROOT, r"资料\脱敏数据_clean\患者3\250111559-TKT\20260217-5.___\202-0.6 x 0.6_BONE"),
    "p3t1": os.path.join(ROOT, r"资料\脱敏数据_clean\患者3\250111559-TKT\20250709\202-1.0 x 0.5_bone"),
}

# 专用任务会输出自己的全部类别；`--roi_subset` 只支持 total/total_mr，
# 因此不能和 head_glands_cavities 一起传给 TotalSegmentator。后处理只取
# 下面三个用于主鼻腔和鼻咽出口的标签。
ROI = ["nasal_cavity_left", "nasal_cavity_right", "nasopharynx"]


def step1_dicom_to_nifti(dcm_dir, nii_path):
    """DICOM → NIfTI，保留完整 geometry。用 Slicer 的 SimpleITK。"""
    code = f'''
import SimpleITK as sitk, json, sys
r = sitk.ImageSeriesReader()
names = r.GetGDCMSeriesFileNames(r"{dcm_dir}")
if not names:
    print(json.dumps({{"ok": False, "why": "no series"}})); sys.exit(0)
r.SetFileNames(names)
img = r.Execute()
sitk.WriteImage(img, r"{nii_path}")
info = {{
  "ok": True,
  "n_files": len(names),
  "size_xyz": list(img.GetSize()),
  "spacing_xyz": list(img.GetSpacing()),
  "origin_xyz": list(img.GetOrigin()),
  "direction": list(img.GetDirection()),
  "pixel_type": str(img.GetPixelIDTypeAsString()),
}}
print(json.dumps(info))
'''
    slicer_py = os.path.join(ROOT, r"软件\slicer\3D Slicer 5.12.4\bin\PythonSlicer.exe")
    p = subprocess.run([slicer_py, "-c", code], capture_output=True, timeout=900)
    out = p.stdout.decode("utf-8", "replace").strip()
    try:
        return json.loads(out.splitlines()[-1])
    except Exception:
        return {"ok": False, "why": "parse fail", "raw": out[-1500:],
                "stderr": p.stderr.decode("utf-8", "replace")[-1500:]}


def step2_totalsegmentator(nii_in, mask_dir, device):
    """调 TotalSegmentator。权重走 hf-mirror。"""
    os.makedirs(mask_dir, exist_ok=True)
    env = os.environ.copy()
    env["HF_ENDPOINT"] = HF_MIRROR
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    # 部分版本用 requests 直连 zenodo，不走 HF；两者都已验证可达
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [TS_EXE, "-i", nii_in, "-o", mask_dir,
           "-ta", "head_glands_cavities", "-d", device]
    log_path = os.path.join(os.path.dirname(mask_dir), "ts_run.log")
    t0 = time.time()
    with open(log_path, "w", encoding="utf-8") as lf:
        lf.write("CMD: " + " ".join(cmd) + "\n")
        lf.write(f"HF_ENDPOINT={HF_MIRROR}\n\n")
        lf.flush()
        p = subprocess.run(cmd, env=env, stdout=lf, stderr=subprocess.STDOUT,
                           timeout=7200)
    return {"ok": p.returncode == 0, "returncode": p.returncode,
            "elapsed_s": round(time.time() - t0, 1), "log": log_path}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    device = "cpu"
    if "--device" in sys.argv:
        device = sys.argv[sys.argv.index("--device") + 1]
        # ★ 坑：--device 的值会混进 args，必须剔除（曾把 "cpu" 当患者键跑出一轮假 step1）
        if device in args:
            args.remove(device)
    keys = [a for a in (args or ["p0"]) if a in PATIENTS] or ["p0"]

    os.makedirs(OUTBASE, exist_ok=True)
    summary = {"device": device, "roi": ROI, "patients": {}}

    for k in keys:
        dcm = PATIENTS.get(k)
        entry = {"dcm_dir": dcm}
        pdir = os.path.join(OUTBASE, k)
        os.makedirs(pdir, exist_ok=True)
        nii = os.path.join(pdir, "ct.nii.gz")

        if dcm and not os.path.isdir(dcm):
            entry["ok"] = False
            entry["why"] = "dcm_dir missing"
            summary["patients"][k] = entry
            print(f"[{k}] SKIP: {dcm}")
            continue

        if os.path.isfile(nii):
            entry["step1"] = {"ok": True, "nii": nii, "note": "pre-existing, skip step1"}
            print(f"[{k}] step1 SKIP (nii exists)")
        else:
            print(f"[{k}] step1 DICOM -> NIfTI ...")
            s1 = step1_dicom_to_nifti(dcm, nii)
            entry["step1"] = s1
            if not s1.get("ok"):
                entry["ok"] = False
                summary["patients"][k] = entry
                print(f"[{k}] step1 FAIL: {s1.get('why') or s1.get('raw','')[:200]}")
                continue
            print(f"[{k}] step1 OK  size={s1['size_xyz']} spacing={[round(v,4) for v in s1['spacing_xyz']]}")

        mask_dir = os.path.join(pdir, "masks")
        print(f"[{k}] step2 TotalSegmentator ({device}) ... (首次会下载权重)")
        s2 = step2_totalsegmentator(nii, mask_dir, device)
        entry["step2"] = s2
        entry["ok"] = bool(s2.get("ok"))
        print(f"[{k}] step2 rc={s2['returncode']} {s2['elapsed_s']}s")
        if os.path.isdir(mask_dir):
            entry["masks"] = sorted(os.listdir(mask_dir))
            print(f"[{k}] masks: {entry['masks']}")
        summary["patients"][k] = entry

    with open(os.path.join(OUTBASE, "run_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("\nSUMMARY ->", os.path.join(OUTBASE, "run_summary.json"))


if __name__ == "__main__":
    main()
