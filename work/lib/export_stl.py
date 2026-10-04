# -*- coding: utf-8 -*-
"""
STL 导出 — 从分割掩膜生成 CFD 可用的几何
==========================================
使用 marching cubes 生成三角网格。
注意：需要保持鼻孔入口和鼻咽出口敞开（CFD 边界条件需要）。
"""
import os, sys, json
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series

OUTDIR = r"D:\项目\鼻腔建模\work\03_mesh"
os.makedirs(OUTDIR, exist_ok=True)


def mask_to_stl(mask, spacing, origin, out_path, smooth_iter=2, decimate=None):
    """
    掩膜 → STL
    smooth_iter: 表面平滑迭代次数（0=不平滑）
    decimate: 目标面数比例（None=不减面）
    """
    try:
        from skimage import measure
    except ImportError:
        return {"ok": False, "error": "skimage 未安装"}

    import struct

    # 可选：平滑
    vol_f = mask.astype(np.float32)
    if smooth_iter > 0:
        vol_f = ndimage.gaussian_filter(vol_f, sigma=smooth_iter)

    # Marching cubes
    verts, faces, normals, values = measure.marching_cubes(
        vol_f, level=0.5, spacing=spacing)

    # 平移回原点坐标系
    verts = verts + np.array(origin)

    # 可选减面
    if decimate and len(faces) > decimate:
        try:
            import open3d as o3d
            mesh = o3d.geometry.TriangleMesh()
            mesh.vertices = o3d.utility.Vector3dVector(verts)
            mesh.triangles = o3d.utility.Vector3iVector(faces)
            mesh = mesh.simplify_quadric_decimation(decimate)
            verts = np.asarray(mesh.vertices)
            faces = np.asarray(mesh.triangles)
        except ImportError:
            pass

    # 写 STL (binary)
    with open(out_path, "wb") as f:
        f.write(b"\0" * 80)
        f.write(struct.pack("<I", len(faces)))
        for tri in faces:
            v0, v1, v2 = verts[tri[0]], verts[tri[1]], verts[tri[2]]
            n = np.cross(v1 - v0, v2 - v0)
            norm = np.linalg.norm(n)
            if norm > 0:
                n = n / norm
            f.write(struct.pack("<3f", *n))
            f.write(struct.pack("<3f", *v0))
            f.write(struct.pack("<3f", *v1))
            f.write(struct.pack("<3f", *v2))
            f.write(struct.pack("<H", 0))

    # STL 闭合性检查
    closed, stats = check_stl_closed(faces, verts)

    return {
        "ok": True,
        "path": out_path,
        "n_verts": len(verts),
        "n_faces": len(faces),
        "bbox_mm": {
            "min": [round(float(v), 2) for v in verts.min(axis=0)],
            "max": [round(float(v), 2) for v in verts.max(axis=0)],
            "size": [round(float(v), 2) for v in (verts.max(axis=0) - verts.min(axis=0))],
        },
        "closed": closed,
        "edge_stats": stats,
    }


def check_stl_closed(faces, verts, tol=0.01):
    """检查 STL 是否闭合（每条边被恰好 2 个三角形共享）"""
    from collections import defaultdict

    edge_count = defaultdict(int)
    for tri in faces:
        for i in range(3):
            a, b = int(tri[i]), int(tri[(i + 1) % 3])
            if a > b:
                a, b = b, a
            edge_count[(a, b)] += 1

    n_edges = len(edge_count)
    n_boundary = sum(1 for c in edge_count.values() if c == 1)
    n_nonmanifold = sum(1 for c in edge_count.values() if c > 2)

    return (n_boundary == 0), {
        "n_edges": n_edges,
        "boundary_edges": n_boundary,
        "nonmanifold_edges": n_nonmanifold,
        "is_closed": n_boundary == 0,
    }


if __name__ == "__main__":
    vol, sp, org, meta = load_dicom_series(
        r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
    print(f"体积 {vol.shape}  间距 {sp}")
    print(f"origin {org}\n")

    # 载入 v9 掩膜
    mask_path = r"D:\项目\鼻腔建模\work\02_segment\nasal_mask_v9.npy"
    mask = np.load(mask_path)
    print(f"掩膜 {mask.shape}  体素 {mask.sum():,}")

    results = {}

    # 变体1：不平滑
    r1 = mask_to_stl(mask, sp, org,
                     os.path.join(OUTDIR, "airway_raw.stl"), smooth_iter=0)
    results["raw"] = r1
    print(f"\n[raw] {json.dumps({k:v for k,v in r1.items() if k!='edge_stats'}, ensure_ascii=False)}")
    if r1["ok"]:
        print(f"      闭合={r1['closed']} 边统计={r1['edge_stats']}")

    # 变体2：平滑 2
    r2 = mask_to_stl(mask, sp, org,
                     os.path.join(OUTDIR, "airway_smooth2.stl"), smooth_iter=2)
    results["smooth2"] = r2
    print(f"\n[smooth2] 面数={r2.get('n_faces')}  闭合={r2.get('closed')}  {r2.get('edge_stats')}")

    # 变体3：平滑 1
    r3 = mask_to_stl(mask, sp, org,
                     os.path.join(OUTDIR, "airway_smooth1.stl"), smooth_iter=1)
    results["smooth1"] = r3
    print(f"\n[smooth1] 面数={r3.get('n_faces')}  闭合={r3.get('closed')}  {r3.get('edge_stats')}")

    with open(os.path.join(OUTDIR, "stl_export_report.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n报告 -> stl_export_report.json")
