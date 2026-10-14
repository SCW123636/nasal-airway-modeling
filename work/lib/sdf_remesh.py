# -*- coding: utf-8 -*-
"""
SDF remesh: closed triangle surface -> signed distance field -> isosurface,
with PATCH LABELS carried over from the input.

Why this route:
    Repairing self-intersections of an existing STL triangle-by-triangle needs a
    trustworthy intersection test, and every test we built was numerically unstable
    (see work/07_cfd_pipeline/自相交定性结论_20261011.md). An isosurface extracted
    from a well-defined signed distance field CANNOT self-intersect -- that is a
    property of the construction, not a measurement. So this sidesteps the unreliable
    instrument entirely and additionally produces a uniform, well-shaped triangulation.

Patch preservation (required for CFD boundary conditions):
    Every output triangle inherits the region label of the NEAREST input triangle
    (nearest centroid). Without this the SDF isosurface would be a single unlabelled
    shell and the nostril_L / nostril_R / nasopharynx_outlet patches would be lost.

Requires VTK (system python 3.10 on this machine: vtk 9.3.1).
"""
import sys, json, argparse, os
import numpy as np

sys.path.insert(0, __file__.rsplit('\\', 1)[0])
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from decide_selfintersection_precision import parse_stl, build_topology
from patch_compare import parse_stl_regions


def write_regions_stl(path, verts, faces, labels):
    """ASCII STL grouped into `solid <label>` blocks."""
    order = {}
    for lab in labels:
        order.setdefault(lab, len(order))
    groups = {}
    for i, lab in enumerate(labels):
        groups.setdefault(lab, []).append(i)
    with open(path, 'w', encoding='utf-8') as f:
        for lab in sorted(groups, key=lambda k: order[k]):
            f.write(f"solid {lab}\n")
            for i in groups[lab]:
                v = verts[faces[i]]
                n = np.cross(v[1] - v[0], v[2] - v[0])
                ln = np.linalg.norm(n)
                n = n / ln if ln > 0 else np.zeros(3)
                f.write(f"  facet normal {n[0]:.9g} {n[1]:.9g} {n[2]:.9g}\n")
                f.write("    outer loop\n")
                for k in range(3):
                    f.write(f"      vertex {v[k][0]:.9g} {v[k][1]:.9g} {v[k][2]:.9g}\n")
                f.write("    endloop\n")
                f.write("  endfacet\n")
            f.write(f"endsolid {lab}\n")
    return {lab: len(v) for lab, v in groups.items()}


def mesh_metrics(V, F):
    p0 = V[F[:, 0]]; p1 = V[F[:, 1]]; p2 = V[F[:, 2]]
    l0 = np.linalg.norm(p1 - p0, axis=1)
    l1 = np.linalg.norm(p2 - p1, axis=1)
    l2 = np.linalg.norm(p0 - p2, axis=1)
    area = 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)
    den = l0 * l0 + l1 * l1 + l2 * l2
    q = np.where(den > 0, 4 * np.sqrt(3) * area / np.where(den > 0, den, 1.0), 0.0)
    stack = np.concatenate([l0, l1, l2])
    a = F[:, 0]; b = F[:, 1]; c = F[:, 2]
    e = np.concatenate([np.sort(np.stack([a, b], 1), 1),
                        np.sort(np.stack([b, c], 1), 1),
                        np.sort(np.stack([c, a], 1), 1)], 0)
    _, cnt = np.unique(e, axis=0, return_counts=True)
    ec = {int(k): int((cnt == k).sum()) for k in np.unique(cnt)}
    return {
        "min_edge_mm": float(stack.min() * 1e3),
        "median_edge_mm": float(np.median(stack) * 1e3),
        "max_edge_mm": float(stack.max() * 1e3),
        "min_quality": float(q.min()),
        "median_quality": float(np.median(q)),
        "surface_area_mm2": float(area.sum() * 1e6),
        "edge_face_counts": ec,
        "closed_manifold": all(k == 2 for k in ec),
        "triangles": int(len(F)),
        "vertices": int(len(V)),
    }


def run(stl_path, out_path, spacing_mm, pad_mm=4.0, report=None,
        assign_patches=True):
    import vtk
    from vtk.util.numpy_support import vtk_to_numpy
    from scipy.spatial import cKDTree

    tris_in, labels_in = parse_stl_regions(stl_path)
    verts, faces = build_topology(np.array(tris_in, dtype=np.float64))
    print(f"[in ] {len(faces)} tris, {len(verts)} verts, "
          f"regions={sorted(set(labels_in))}")
    m_in = mesh_metrics(verts, faces)
    print(f"[in ] min_edge={m_in['min_edge_mm']:.4f} mm  "
          f"min_q={m_in['min_quality']:.3e}  area={m_in['surface_area_mm2']:.1f} mm2")

    pts = vtk.vtkPoints()
    pts.SetDataTypeToDouble()
    for v in verts:
        pts.InsertNextPoint(float(v[0]), float(v[1]), float(v[2]))
    cell = vtk.vtkCellArray()
    for f in faces:
        cell.InsertNextCell(3)
        for k in range(3):
            cell.InsertCellPoint(int(f[k]))
    poly = vtk.vtkPolyData()
    poly.SetPoints(pts)
    poly.SetPolys(cell)

    imp = vtk.vtkImplicitPolyDataDistance()
    imp.SetInput(poly)
    # NOTE: VTK 9.3 has no SetSignedDistance(); this class is signed by construction
    # (negative inside), which is what we need.

    b = np.zeros(6)
    poly.GetBounds(b)
    pad = pad_mm * 1e-3
    bounds = (b[0] - pad, b[1] + pad, b[2] - pad, b[3] + pad, b[4] - pad, b[5] + pad)
    ext = [bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]]
    dims = [max(8, int(np.ceil(e / (spacing_mm * 1e-3)))) + 1 for e in ext]
    print(f"[grid] extent_mm={[round(e * 1e3, 2) for e in ext]}  dims={dims}  "
          f"voxels={dims[0] * dims[1] * dims[2]:,}")

    samp = vtk.vtkSampleFunction()
    samp.SetImplicitFunction(imp)
    samp.SetModelBounds(*bounds)
    samp.SetSampleDimensions(*dims)
    samp.SetCapping(False)
    samp.ComputeNormalsOff()
    samp.Update()

    fe = vtk.vtkFlyingEdges3D()
    fe.SetInputConnection(samp.GetOutputPort())
    fe.SetValue(0, 0.0)
    fe.ComputeNormalsOff()
    fe.ComputeGradientsOff()
    fe.Update()
    out = fe.GetOutput()
    print(f"[iso ] {out.GetNumberOfCells()} tris, {out.GetNumberOfPoints()} verts")

    V = vtk_to_numpy(out.GetPoints().GetData()).astype(np.float64)
    C = vtk_to_numpy(out.GetPolys().GetData()).reshape(-1, 4)
    assert (C[:, 0] == 3).all(), "non-triangular cell found"
    F = C[:, 1:4].astype(np.int64)

    labels = None
    if assign_patches:
        cent_in = verts[faces].mean(axis=1)
        tree = cKDTree(cent_in)
        _, nn = tree.query(V[F].mean(axis=1), k=1)
        labels = [labels_in[i] for i in nn]
        print("[lab ] patches assigned from nearest input triangle")

    d = os.path.dirname(os.path.abspath(out_path))
    if d:
        os.makedirs(d, exist_ok=True)
    if labels is not None:
        pcount = write_regions_stl(out_path, V, F, labels)
    else:
        pcount = write_regions_stl(out_path, V, F, ["ALL"] * len(F))

    m_out = mesh_metrics(V, F)
    res = {
        "input": stl_path, "output": out_path,
        "spacing_mm": spacing_mm, "pad_mm": pad_mm, "grid_dims": dims,
        "input_metrics": m_in,
        "output_metrics": m_out,
        "patch_counts_out": pcount,
        "self_intersection": "not_needed__isosurface_of_sdf_cannot_self_intersect",
    }
    if labels is not None:
        a = 0.5 * np.linalg.norm(
            np.cross(V[F][:, 1] - V[F][:, 0], V[F][:, 2] - V[F][:, 0]), axis=1)
        pstat = {}
        for lab in sorted(set(labels)):
            m = np.array([l == lab for l in labels])
            pstat[lab] = {"triangles": int(m.sum()),
                          "area_mm2": float(a[m].sum() * 1e6)}
        res["patch_areas_out"] = pstat
        ain = 0.5 * np.linalg.norm(
            np.cross(verts[faces][:, 1] - verts[faces][:, 0],
                     verts[faces][:, 2] - verts[faces][:, 0]), axis=1)
        istat = {}
        for lab in sorted(set(labels_in)):
            m = np.array([l == lab for l in labels_in])
            istat[lab] = {"triangles": int(m.sum()),
                          "area_mm2": float(ain[m].sum() * 1e6)}
        res["patch_areas_in"] = istat

    print(json.dumps({k: v for k, v in res.items()
                      if k != "input_metrics"}, indent=2))
    if report:
        with open(report, 'w', encoding='utf-8') as f:
            json.dump(res, f, indent=2)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stl', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--spacing-mm', type=float, default=0.35)
    ap.add_argument('--pad-mm', type=float, default=4.0)
    ap.add_argument('--report', default=None)
    ap.add_argument('--no-patches', action='store_true')
    a = ap.parse_args()
    run(a.stl, a.out, a.spacing_mm, a.pad_mm, a.report,
        assign_patches=not a.no_patches)


if __name__ == '__main__':
    main()
