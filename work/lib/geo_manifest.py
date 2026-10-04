# -*- coding: utf-8 -*-
"""几何保真脚手架：分割标签体 (NIfTI) -> 候选表面 + manifest.json。

用途
----
把分割标签体（NIfTI，带 spacing/origin/direction）转成候选表面，需审核，
并写出保留全部几何信息的 manifest.json（单位、坐标系、4x4 仿射、
SeriesInstanceUID、阈值、重采样间距、平滑/抽稀参数、裁剪面、开口状态）。

命令行用法
----------
python geo_manifest.py \
    --label  path/to/airway_label.nii.gz   # 分割标签体（NIfTI，必填）
    --series-uid 1.2.826.0.1....           # 来源 SeriesInstanceUID（必填）
    --threshold 1                          # 要提取的标签值（等值提取，默认 1）
    --resample 0.35                        # 各向同性重采样间距 mm；0 = 不重采样
    --out work/04_cfd_ready/case01         # 输出目录

表面生成策略（graceful degrade，不强装 VTK）
-------------------------------------------
1. 若 venv 里有 vtk：sitk 标签体 -> vtkDiscreteMarchingCubes -> .vtp（真实网格）。
2. 若无 vtk：退化用 SimpleITK LabelContour 生成边界 mask，写 .mha 占位，
   manifest 中 surface_placeholder=true，报告需标注
   「真实网格生成依赖 VTK，当前为 mask 占位」。

self-check（任一不过则退出码非 0）
---------------------------------
- manifest.json 能重新 json.load；
- affine 是 4x4 且底行为 [0,0,0,1]；
- 若生成了表面：vtp 顶点数 > 0；若为 mask 占位：轮廓体素数 > 0。

坐标系约定：本项目默认 LPS（ITK/DICOM 物理坐标）；Slicer 内部为 RAS。
"""
import argparse
import importlib.util
import json
import os
import shutil
import sys
import tempfile

import numpy as np
import SimpleITK as sitk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dicom_sitk import load_series_sitk  # noqa: F401  复用项目读序列入口（供上游链路调用）

HAS_VTK = importlib.util.find_spec("vtk") is not None

OPENING_STATUS_TEMPLATE = [
    {"opening": "nostril_L",  "type": "inlet",        "status": "unknown", "note": "待 ENT 确认"},
    {"opening": "nostril_R",  "type": "inlet",        "status": "unknown", "note": "待 ENT 确认"},
    {"opening": "nasopharynx", "type": "outlet",      "status": "unknown", "note": "待 ENT 确认"},
    {"opening": "maxillary_sinus_ostium", "type": "sinus", "status": "unknown", "note": "待 ENT 确认"},
    {"opening": "frontal_sinus_ostium",   "type": "sinus", "status": "unknown", "note": "待 ENT 确认"},
    {"opening": "ethmoid_sinus_ostia",    "type": "sinus", "status": "unknown", "note": "待 ENT 确认"},
    {"opening": "sphenoid_sinus_ostium",  "type": "sinus", "status": "unknown", "note": "待 ENT 确认"},
]


def build_affine(spacing, origin, direction):
    """从 spacing/origin/direction 构造 4x4 numpy 矩阵（通用形式）。

    A[:3,:3] = direction(3x3, 行主序) @ diag(spacing)；A[:3,3] = origin。
    LPS 轴对齐时 direction 为单位阵，退化为对角形式。
    """
    d = np.asarray(direction, dtype=float).reshape(3, 3)
    s = np.diag(np.asarray(spacing, dtype=float))
    a = np.eye(4, dtype=float)
    a[:3, :3] = d @ s
    a[:3, 3] = np.asarray(origin, dtype=float)
    return a


def resample_isotropic(img, iso_mm):
    """把标签体重采样到各向同性 iso_mm（最近邻，保持标签值）。"""
    sp = img.GetSpacing()
    size = img.GetSize()
    new_size = [int(round(size[i] * sp[i] / iso_mm)) for i in range(3)]
    new_size = [max(n, 1) for n in new_size]
    rs = sitk.ResampleImageFilter()
    rs.SetOutputSpacing([iso_mm] * 3)
    rs.SetSize(new_size)
    rs.SetOutputOrigin(img.GetOrigin())
    rs.SetOutputDirection(img.GetDirection())
    rs.SetInterpolator(sitk.sitkNearestNeighbor)
    rs.SetDefaultPixelValue(0)
    return rs.Execute(img)


def extract_label_mask(label_img, label_value):
    """等值提取某个标签 -> 0/1 mask（uint8）。"""
    return sitk.Cast(label_img == int(label_value), sitk.sitkUInt8)


def make_surface_vtp(mask_img, out_vtp):
    """0/1 mask -> 原索引范围内提取 -> 完整 LPS 仿射 -> 候选 .vtp，需审核。

    不扩展体数据、不封洞、不裁剪；反射仿射后反转面绕序，保持外向约定。
    返回顶点数，不代表表面已通过解剖或 CFD 审核。
    """
    import vtk
    from vtk.util.numpy_support import numpy_to_vtk

    arr = sitk.GetArrayFromImage(mask_img)  # (z,y,x)
    vtk_arr = numpy_to_vtk(arr.ravel(order="C"), deep=True)
    im = vtk.vtkImageData()
    im.SetDimensions(arr.shape[::-1])
    # Extract in XYZ index space; apply spacing, direction and origin exactly once.
    im.SetSpacing(1.0, 1.0, 1.0)
    im.SetOrigin(0.0, 0.0, 0.0)
    im.GetPointData().SetScalars(vtk_arr)

    mc = vtk.vtkDiscreteMarchingCubes()
    mc.SetInputData(im)
    mc.SetValue(0, 1)
    mc.Update()

    affine = build_affine(mask_img.GetSpacing(), mask_img.GetOrigin(), mask_img.GetDirection())
    matrix = vtk.vtkMatrix4x4()
    for row in range(4):
        for col in range(4):
            matrix.SetElement(row, col, float(affine[row, col]))
    transform = vtk.vtkTransform()
    transform.SetMatrix(matrix)
    physical = vtk.vtkTransformFilter()
    physical.SetInputConnection(mc.GetOutputPort())
    physical.SetTransform(transform)
    physical.SetOutputPointsPrecision(vtk.vtkAlgorithm.DOUBLE_PRECISION)
    output = physical
    if np.linalg.det(affine[:3, :3]) < 0:
        reverse = vtk.vtkReverseSense()
        reverse.SetInputConnection(physical.GetOutputPort())
        reverse.ReverseCellsOn()
        # Transformed normals already follow inverse-transpose; only winding flips.
        reverse.ReverseNormalsOff()
        output = reverse

    w = vtk.vtkXMLPolyDataWriter()
    w.SetFileName(out_vtp)
    w.SetInputConnection(output.GetOutputPort())
    w.Write()
    return mc.GetOutput().GetNumberOfPoints()


def make_contour_mask_mha(mask_img, out_mha):
    """无 VTK 退化路径：LabelContour 边界 mask -> .mha 占位。返回轮廓体素数。"""
    contour = sitk.LabelContour(mask_img, fullyConnected=True)
    sitk.WriteImage(contour, out_mha)
    n = int(np.count_nonzero(sitk.GetArrayFromImage(contour)))
    return n


def lookup_affine_summary(series_uid, project_work=None):
    """尽力在 work/01_inspect/affine_summary.json 里按 UID 查真实序列几何，查不到返回 None。"""
    if project_work is None:
        project_work = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(project_work, "01_inspect", "affine_summary.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            for item in json.load(f):
                if item.get("series_instance_uid") == series_uid:
                    return item
    except Exception:
        return None
    return None


def _is_ascii(path):
    try:
        path.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


class AsciiStage:
    """SimpleITK 2.5.6 官方二进制在非 ASCII 路径下读写 NIfTI/MHA 会失败
    （本机实测：中文项目目录下 ReadImage/WriteImage 均抛 Unable to open）。
    此上下文管理器把输入拷贝到 ASCII 临时目录处理，输出先写临时文件再拷回。"""

    def __init__(self, *paths_to_stage):
        self._tmpdir = tempfile.TemporaryDirectory(prefix="geo_manifest_")
        self._dir = self._tmpdir.name
        self.staged = []
        for p in paths_to_stage:
            if _is_ascii(p):
                self.staged.append(p)
            else:
                dst = os.path.join(self._dir, "input_%d%s" % (len(self.staged), os.path.splitext(p)[1]))
                if p.endswith(".nii.gz"):
                    dst += ".nii.gz"
                shutil.copyfile(p, dst)
                self.staged.append(dst)

    def tmp_output(self, filename):
        return os.path.join(self._dir, filename)

    def cleanup(self):
        self._tmpdir.cleanup()


def main():
    ap = argparse.ArgumentParser(description="标签体 -> 候选表面（需审核）+ 几何保真 manifest")
    ap.add_argument("--label", required=True, help="分割标签 NIfTI 路径 (.nii/.nii.gz)")
    ap.add_argument("--series-uid", required=True, help="来源 SeriesInstanceUID")
    ap.add_argument("--threshold", type=int, default=1, help="要提取的标签值（等值），默认 1")
    ap.add_argument("--resample", type=float, default=0.35,
                    help="各向同性重采样间距 mm，默认 0.35；0 = 不重采样")
    ap.add_argument("--out", required=True, help="输出目录")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    stage = AsciiStage(args.label)
    try:
        return _run(args, stage)
    finally:
        stage.cleanup()


def _run(args, stage):
    # 1) 读标签体（经 ASCII 暂存，绕开 sitk 中文路径读写失败）
    label_img = sitk.ReadImage(stage.staged[0])
    spacing = label_img.GetSpacing()
    origin = label_img.GetOrigin()
    direction = label_img.GetDirection()
    affine = build_affine(spacing, origin, direction)

    arr = sitk.GetArrayFromImage(label_img)
    labels_present = sorted(int(v) for v in np.unique(arr) if v != 0)
    if args.threshold not in labels_present:
        print(f"[geo] 警告：标签值 {args.threshold} 不在体数据标签 {labels_present} 中", flush=True)

    # 2) 重采样（可选）
    resampled = None
    resample_mm = None
    work_img = label_img
    if args.resample and args.resample > 0:
        resampled = resample_isotropic(label_img, args.resample)
        resample_mm = float(args.resample)
        work_img = resampled

    # 3) 提取二值 mask
    mask = extract_label_mask(work_img, args.threshold)
    n_mask_voxels = int(np.count_nonzero(sitk.GetArrayFromImage(mask)))

    # 4) 表面生成（VTK 优先，否则 mask 占位）
    surface_path = None
    surface_placeholder = False
    n_vertices = None
    contour_voxels = None
    if HAS_VTK:
        surface_path = os.path.join(args.out, "surface.vtp")
        write_path = surface_path if _is_ascii(surface_path) else stage.tmp_output("surface.vtp")
        n_vertices = make_surface_vtp(mask, write_path)
        if write_path != surface_path:
            shutil.copyfile(write_path, surface_path)
    else:
        surface_path = os.path.join(args.out, "contour_mask.mha")
        write_path = surface_path if _is_ascii(surface_path) else stage.tmp_output("contour_mask.mha")
        contour_voxels = make_contour_mask_mha(mask, write_path)
        if write_path != surface_path:
            shutil.copyfile(write_path, surface_path)
        surface_placeholder = True
        print("[geo] 未检测到 vtk，退化为 LabelContour mask 占位（非真实网格）", flush=True)

    # 5) manifest
    uid_hit = lookup_affine_summary(args.series_uid)
    manifest = {
        "schema": "geo_manifest/v1",
        "unit": "mm",
        "coordinate_system": "LPS",
        "note_ras": "Slicer 内部为 RAS；本 manifest 与输出文件均为 ITK/DICOM LPS 物理坐标",
        "source_series_uid": args.series_uid,
        "label_image": os.path.abspath(args.label),
        "threshold_label_value": args.threshold,
        "labels_present_in_volume": labels_present,
        "input_geometry": {
            "spacing_xyz_mm": [float(v) for v in spacing],
            "origin_xyz_mm": [float(v) for v in origin],
            "direction_3x3_row_major": [float(v) for v in direction],
        },
        "affine_4x4_LPS": [[float(v) for v in row] for row in affine.tolist()],
        "resample_spacing_mm": resample_mm,
        "resampled_geometry": ({
            "spacing_xyz_mm": [float(v) for v in resampled.GetSpacing()],
            "size_xyz": [int(v) for v in resampled.GetSize()],
        } if resampled is not None else None),
        "smoothing_mm": None,           # 待实际平滑后填写
        "decimation_ratio": None,       # 待实际抽稀后填写
        "clip_plane_position": None,    # 解剖裁剪面（后鼻孔/鼻咽），待 ENT 确认后填写
        "opening_status_list": OPENING_STATUS_TEMPLATE,
        "mask_voxel_count_label": n_mask_voxels,
        "surface": {
            "path": os.path.abspath(surface_path),
            "format": "vtp" if not surface_placeholder else "mha",
            "surface_placeholder": surface_placeholder,
            "placeholder_reason": ("真实网格生成依赖 VTK，当前 venv 无 vtk，"
                                   "以 LabelContour 边界 mask 占位") if surface_placeholder else None,
            "n_vertices": n_vertices,
            "contour_voxels": contour_voxels,
        },
        "affine_summary_match": ({"label": uid_hit["label"], "path": uid_hit["path"]}
                                 if uid_hit else None),
    }

    manifest_path = os.path.join(args.out, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 6) self-check
    errors = []

    # 6a) manifest 能重新 json.load
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            reloaded = json.load(f)
    except Exception as e:
        errors.append(f"manifest 重新 json.load 失败: {e}")
        reloaded = None

    # 6b) affine 是 4x4 且底行 [0,0,0,1]
    if reloaded is not None:
        a = np.asarray(reloaded["affine_4x4_LPS"], dtype=float)
        if a.shape != (4, 4):
            errors.append(f"affine 形状不是 4x4: {a.shape}")
        elif not np.allclose(a[3], [0, 0, 0, 1]):
            errors.append(f"affine 底行异常: {a[3].tolist()}")

    # 6c) 表面顶点数 > 0（或占位 mask 轮廓体素数 > 0）
    if not surface_placeholder:
        if not (n_vertices and n_vertices > 0):
            errors.append(f"vtp 顶点数异常: {n_vertices}")
    else:
        if not (contour_voxels and contour_voxels > 0):
            errors.append(f"占位轮廓 mask 体素数异常: {contour_voxels}")

    print(json.dumps({
        "self_check": "PASS" if not errors else "FAIL",
        "errors": errors,
        "vtk_available": HAS_VTK,
        "surface_placeholder": surface_placeholder,
        "n_vertices": n_vertices,
        "contour_voxels": contour_voxels,
        "mask_voxels": n_mask_voxels,
        "labels_present": labels_present,
        "manifest": os.path.abspath(manifest_path),
        "surface": os.path.abspath(surface_path),
    }, ensure_ascii=False, indent=2))

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
