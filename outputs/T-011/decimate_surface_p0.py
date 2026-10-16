# -*- coding: utf-8 -*-
"""T-011 p0 meshing-input step: reduce the WALL triangle count before netgen.

Why this exists
---------------
p0 (example 0, the ISO_Bone 0.35 mm isotropic base) has a marching-cubes surface
of 438,028 triangles - 2.5x b15's 175,204 - because its source CT is far finer
than the b-cohort's. netgen's peak RSS scales with the STL facet count (measured:
it was OOM-killed at 7.34 GB with an 8 GB cap and at 10.48 GB with an 11 GB cap,
and --maxh 1.0 and --maxh 5.0 cost the SAME memory, so maxh cannot help). The
host has 15.7 GB total, so the mesh cannot be built as-is.

What it does NOT change
-----------------------
Only the `wall` cells are decimated. The three opening caps (nostril_L,
nostril_R, oropharynx_truncation_outlet) are copied through EXACTLY, so the
opening areas - the CFD inlet/outlet areas and the "known answers" netgen
verifies its boundary labelling against - are unchanged. Boundary vertices of
the wall (the cap rims) are protected, so the caps stay welded by coordinate
coincidence (STL is a triangle soup; netgen welds by proximity).

This is a meshing-INPUT transformation for p0 only. The production surface
construction path (marching cubes / HU -300 / mask_surface) is untouched, per
the T-058 ruling. The source auto_placed.vtp is never overwritten.

Usage:  python decimate_surface_p0.py <auto_placed.vtp> <out.vtp> [--target-total 160000] [--report r.json]
"""
import argparse
import collections
import json
from pathlib import Path

import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy


def read_poly(path):
    r = vtk.vtkXMLPolyDataReader()
    r.SetFileName(str(path))
    r.Update()
    return r.GetOutput()


def cell_triangles(poly):
    """(n_cells, 3) int64 connectivity for a pure-triangle polydata, plus labels."""
    polys = poly.GetPolys()
    if polys is None or polys.GetNumberOfCells() == 0:
        raise SystemExit('no polygons in source')
    ids = polys.GetData()
    tris, i, N = [], 0, ids.GetNumberOfTuples()
    while i < N:
        k = ids.GetValue(i); i += 1
        if k != 3:
            raise SystemExit(f'non-triangle cell of size {k}; this tool assumes triangles')
        tris.append((ids.GetValue(i), ids.GetValue(i + 1), ids.GetValue(i + 2)))
        i += 3
    arr = poly.GetCellData().GetAbstractArray('boundary_patch')
    if arr is None:
        raise SystemExit('no boundary_patch cell array - refusing')
    labels = [arr.GetValue(c) for c in range(poly.GetNumberOfCells())]
    return np.asarray(tris, dtype=np.int64), labels


def make_poly(points, cells):
    pd = vtk.vtkPolyData()
    vp = vtk.vtkPoints()
    vp.SetData(numpy_to_vtk(np.ascontiguousarray(points, dtype=float), deep=1))
    pd.SetPoints(vp)
    ca = vtk.vtkCellArray()
    for tri in cells:
        ca.InsertNextCell(3)
        for p in tri:
            ca.InsertCellPoint(int(p))
    pd.SetPolys(ca)
    return pd


def triangle_areas(points, cells):
    p = points[cells]
    u, v = p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]
    return 0.5 * np.linalg.norm(np.cross(u, v), axis=1)


def open_edges(points, cells, tol=1e-6):
    """Edges used exactly once (a watertight closed surface has none)."""
    key = lambda a: tuple(np.round(a / tol).astype(np.int64))
    cnt = collections.Counter()
    for tri in cells:
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            ka, kb = key(points[a]), key(points[b])
            cnt[(ka, kb) if ka <= kb else (kb, ka)] += 1
    return sum(1 for v in cnt.values() if v == 1), sum(1 for v in cnt.values() if v > 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source')
    ap.add_argument('out')
    ap.add_argument('--target-total', type=int, default=160000,
                    help='target TOTAL triangle count after decimation')
    ap.add_argument('--report', default=None)
    args = ap.parse_args()

    poly = read_poly(args.source)
    points = vtk_to_numpy(poly.GetPoints().GetData()).astype(float)
    cells, labels = cell_triangles(poly)
    labels = np.asarray(labels)

    wall_idx = np.where(labels == 'wall')[0]
    cap_idx = np.where(labels != 'wall')[0]
    wall_cells = cells[wall_idx]
    cap_cells = cells[cap_idx]
    cap_labels = [labels[i] for i in cap_idx]

    target_wall = max(1000, args.target_total - len(cap_cells))
    reduction = 1.0 - target_wall / float(len(wall_cells))
    reduction = min(max(reduction, 0.0), 0.95)

    # --- decimate the wall only ---
    wp = make_poly(points, wall_cells)
    cl = vtk.vtkCleanPolyData()
    cl.SetInputData(wp)
    cl.PointMergingOn()
    cl.SetTolerance(1e-6)
    cl.Update()
    dec = vtk.vtkDecimatePro()
    dec.SetInputConnection(cl.GetOutputPort())
    dec.SetTargetReduction(reduction)
    dec.SetPreserveTopology(True)
    dec.BoundaryVertexDeletionOff()   # keep the cap rims exactly where they are
    dec.SplittingOff()
    dec.SetMaximumError(1e9)
    dec.Update()
    w = dec.GetOutput()
    w_pts = vtk_to_numpy(w.GetPoints().GetData()).astype(float)
    # the decimator output carries no boundary_patch array; read connectivity raw
    ids = w.GetPolys().GetData()
    tris, i = [], 0
    while i < ids.GetNumberOfTuples():
        k = ids.GetValue(i); i += 1
        if k != 3:
            raise SystemExit(f'decimator emitted a non-triangle ({k})')
        tris.append((ids.GetValue(i), ids.GetValue(i + 1), ids.GetValue(i + 2))); i += 3
    w_cells = np.asarray(tris, dtype=np.int64)

    # --- merge: caps (original ids) + decimated wall (offset ids) ---
    off = len(points)
    out_pts = np.vstack([points, w_pts])
    out_cells = np.vstack([cap_cells, w_cells + off])
    out_labels = list(cap_labels) + ['wall'] * len(w_cells)

    out = make_poly(out_pts, out_cells)
    la = vtk.vtkStringArray()
    la.SetName('boundary_patch')
    for lab in out_labels:
        la.InsertNextValue(lab)
    out.GetCellData().AddArray(la)
    wr = vtk.vtkXMLPolyDataWriter()
    wr.SetFileName(args.out)
    wr.SetInputData(out)
    wr.Write()

    # --- checks ---
    area_by = collections.defaultdict(float)
    a = triangle_areas(out_pts, out_cells)
    for lab, ar in zip(out_labels, a):
        area_by[lab] += float(ar)
    src_area = collections.defaultdict(float)
    sa = triangle_areas(points, cells)
    for lab, ar in zip(labels, sa):
        src_area[lab] += float(ar)
    ne, nonman = open_edges(out_pts, out_cells)

    report = {
        'source': str(args.source), 'out': str(args.out),
        'target_total': args.target_total, 'target_reduction_wall': round(reduction, 4),
        'triangles_in': int(len(cells)), 'triangles_out': int(len(out_cells)),
        'wall_in': int(len(wall_cells)), 'wall_out': int(len(w_cells)),
        'caps_in': int(len(cap_cells)), 'caps_out': int(len(cap_cells)),
        'patch_area_in_mm2': {k: round(v, 4) for k, v in sorted(src_area.items())},
        'patch_area_out_mm2': {k: round(v, 4) for k, v in sorted(area_by.items())},
        'cap_area_delta_pct': {k: round((area_by[k] - src_area[k]) / src_area[k] * 100.0, 4)
                               for k in ('nostril_L', 'nostril_R', 'oropharynx_truncation_outlet')},
        'open_edges': ne, 'nonmanifold_edges': nonman,
        'note': ('caps copied exactly (areas are the input areas); wall quadric-decimated. '
                 'open_edges counts coordinate-welded edges used once - a watertight closed '
                 'surface must be 0.'),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
