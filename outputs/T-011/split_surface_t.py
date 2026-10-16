# -*- coding: utf-8 -*-
"""T-011 A.2 - parameterized split of a p0 threshold-axis surface into per-patch
STLs + interior point. Same logic as split_surface_for_snappy.py (A.1), argv-driven:
  python split_surface_t.py <src_vtp> <outdir>
Writes <outdir>/{nostril_L,nostril_R,oropharynx_truncation_outlet,wall}.stl and
<outdir>/../split_report_t.json (locationInMesh in mm, bbox).
"""
import json
import os
import sys

import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy

SRC = sys.argv[1]
OUTDIR = sys.argv[2]
PATCHES = ('nostril_L', 'nostril_R', 'oropharynx_truncation_outlet', 'wall')


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    r = vtk.vtkXMLPolyDataReader()
    r.SetFileName(SRC)
    r.Update()
    poly = r.GetOutput()
    pts = poly.GetPoints()
    P = vtk_to_numpy(pts.GetData()).astype(float)
    n = poly.GetNumberOfCells()
    arr = poly.GetCellData().GetAbstractArray('boundary_patch')
    lab = [arr.GetValue(i) for i in range(n)]

    polys = poly.GetPolys().GetData()
    tris, i = [], 0
    while i < polys.GetNumberOfTuples():
        k = polys.GetValue(i); i += 1
        if k != 3:
            raise SystemExit('non-triangle cell size %d' % k)
        tris.append((polys.GetValue(i), polys.GetValue(i + 1), polys.GetValue(i + 2)))
        i += 3
    assert len(tris) == n, (len(tris), n)

    print('source      : %s' % SRC)
    print('points/tris : %d / %d' % (len(P), n))

    areas = {}
    for name in PATCHES:
        ids = [c for c in range(n) if lab[c] == name]
        ca = vtk.vtkCellArray()
        for c in ids:
            ca.InsertNextCell(3)
            for p in tris[c]:
                ca.InsertCellPoint(p)
        pd = vtk.vtkPolyData()
        pd.SetPoints(pts)
        pd.SetPolys(ca)
        path = os.path.join(OUTDIR, name + '.stl')
        w = vtk.vtkSTLWriter()
        w.SetFileName(path)
        w.SetFileTypeToBinary()
        w.SetInputData(pd)
        w.Write()
        sel = np.array([tris[c] for c in ids])
        u = P[sel[:, 1]] - P[sel[:, 0]]
        v = P[sel[:, 2]] - P[sel[:, 0]]
        a = 0.5 * np.linalg.norm(np.cross(u, v), axis=1).sum()
        areas[name] = round(float(a), 4)
        print('  %-30s %7d tris  %10.4f mm^2' % (name, len(ids), a))

    lo, hi = P.min(axis=0), P.max(axis=0)
    step = 2.0
    gx, gy, gz = np.meshgrid(np.arange(lo[0] + 1, hi[0], step),
                             np.arange(lo[1] + 1, hi[1], step),
                             np.arange(lo[2] + 1, hi[2], step), indexing='ij')
    grid = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])
    print('interior probe: %d grid points at %.1f mm' % (len(grid), step))

    vp = vtk.vtkPoints()
    vp.SetData(numpy_to_vtk(np.ascontiguousarray(grid), deep=1))
    pcloud = vtk.vtkPolyData()
    pcloud.SetPoints(vp)
    verts = vtk.vtkCellArray()
    for k in range(len(grid)):
        verts.InsertNextCell(1)
        verts.InsertCellPoint(k)
    pcloud.SetVerts(verts)

    sel = vtk.vtkSelectEnclosedPoints()
    sel.SetInputData(pcloud)
    sel.SetSurfaceData(poly)
    sel.SetTolerance(0.0)
    sel.Update()
    sa = sel.GetOutput().GetPointData().GetArray('SelectedPoints')
    mask = np.array([bool(sa.GetTuple1(k)) for k in range(len(grid))])
    gin = grid[mask]
    print('  inside points: %d' % len(gin))
    if len(gin) == 0:
        raise SystemExit('no interior grid point found - inspect the surface')

    sur = P[np.unique(np.array(tris).ravel())]
    try:
        from scipy.spatial import cKDTree
        d, _ = cKDTree(sur).query(gin)
    except Exception:
        d = np.empty(len(gin))
        for k in range(0, len(gin), 500):
            blk = gin[k:k + 500]
            d[k:k + 500] = np.sqrt(((blk[:, None, :] - sur[None, :, :]) ** 2)
                                   .sum(-1)).min(axis=1)
    chosen = gin[int(np.argmax(d))]
    print('locationInMesh = (%.5f %.5f %.5f)  clearance %.4f mm'
          % (chosen[0], chosen[1], chosen[2], float(d.max())))

    rep = {
        'source': SRC,
        'points': int(len(P)), 'triangles': int(n),
        'patch_triangle_counts': {k: sum(1 for l in lab if l == k) for k in PATCHES},
        'patch_areas_mm2': areas,
        'stl_dir': OUTDIR,
        'locationInMesh': [float(x) for x in chosen],
        'bbox_mm': {'min': P.min(axis=0).tolist(), 'max': P.max(axis=0).tolist()},
    }
    with open(os.path.join(OUTDIR, '..', 'split_report_t%s.json'
                           % os.path.basename(OUTDIR).replace('snappy_', '')), 'w') as fh:
        json.dump(rep, fh, indent=2)
    print('wrote split report')


if __name__ == '__main__':
    main()
