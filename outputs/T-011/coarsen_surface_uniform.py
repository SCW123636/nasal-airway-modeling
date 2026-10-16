# -*- coding: utf-8 -*-
"""T-011 meshing-input step 2: collapse sub-tolerance edges so netgen cannot
run away on slivers.

Diagnosis this addresses
------------------------
The p0 surface (both the original 438,028-triangle marching-cubes output and its
160,000-triangle vtkDecimatePro reduction, outputs/T-011/inspect_stl.py) carries
a handful of sliver triangles whose shortest edge is ~0.00046 mm - three orders
of magnitude below the ~0.49 mm median edge. netgen sizes its surface elements
from the LOCAL STL edge, so each such edge asks for sub-micron refinement; the
result is a slow local element explosion (the decimated run grew for 15 min
before the OOM killer took it at ~10.5 GB). Triangle COUNT is not the driver:
reducing 438,028 -> 160,000 triangles left the min edge (0.000462 mm) and the
sliver population essentially unchanged, and netgen's memory did not move.

What this does
--------------
Pure-numpy, label-free: parse ASCII STL -> weld coordinates onto a grid of side
`tol` (an edge collapse: every vertex snaps to the representative of its grid
cell) -> drop triangles that became degenerate (two or three equal vertices) ->
measure watertightness with an undirected-edge census -> write ASCII STL. The
caps are not special-cased here; they are welded like everything else. A
coordinate-welded closed surface must have ZERO edges used once.

Verify with outputs/T-011/inspect_stl.py afterwards: the goal is min edge >= tol
(near) with open edges == 0.

Usage: python3 coarsen_surface_uniform.py <in.stl> <out.stl> [--tol 0.06]
"""
import argparse
import collections
from pathlib import Path

import numpy as np


def load_ascii_stl(path):
    tris, cur = [], []
    with open(path, 'r', errors='ignore') as f:
        for line in f:
            s = line.strip()
            if s.startswith('vertex'):
                cur.append([float(x) for x in s.split()[1:4]])
                if len(cur) == 3:
                    tris.append(cur)
                    cur = []
    return np.asarray(tris, dtype=float)


def write_ascii_stl(path, tris, name='coarsened'):
    with open(path, 'w') as f:
        f.write('solid %s\n' % name)
        for t in tris:
            u = t[1] - t[0]
            v = t[2] - t[0]
            n = np.cross(u, v)
            ln = np.linalg.norm(n)
            n = n / ln if ln > 0 else np.zeros(3)
            f.write('  facet normal %.6e %.6e %.6e\n' % tuple(n))
            f.write('    outer loop\n')
            for p in t:
                f.write('      vertex %.6f %.6f %.6f\n' % tuple(p))
            f.write('    endloop\n')
            f.write('  endfacet\n')
        f.write('endsolid %s\n' % name)


def weld(tris, tol):
    """Snap every vertex to the representative of its tol-sized grid cell."""
    V = tris.reshape(-1, 3)
    key = np.round(V / tol).astype(np.int64)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    pts = uniq.astype(float) * tol
    tri = inv.reshape(-1, 3)
    # drop degenerate (two or three identical welded vertices)
    keep = (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])
    return pts, tri[keep], int((~keep).sum())


def edge_census(tri):
    cnt = collections.Counter()
    for a, b, c in tri:
        for x, y in ((a, b), (b, c), (c, a)):
            cnt[(x, y) if x < y else (y, x)] += 1
    once = sum(1 for v in cnt.values() if v == 1)
    over = sum(1 for v in cnt.values() if v > 2)
    return once, over, len(cnt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source')
    ap.add_argument('out')
    ap.add_argument('--tol', type=float, default=0.06,
                    help='edge-collapse tolerance in mm (grid cell side)')
    args = ap.parse_args()

    tris = load_ascii_stl(args.source)
    pts, tri, dropped = weld(tris, args.tol)
    once, over, ne = edge_census(tri)

    # write the welded representative coordinates back per triangle
    out = pts[tri]
    write_ascii_stl(args.out, out)

    print('source triangles      : %d' % len(tris))
    print('tol (mm)              : %.4f' % args.tol)
    print('welded unique points  : %d' % len(pts))
    print('degenerate dropped    : %d' % dropped)
    print('triangles out         : %d' % len(tri))
    print('undirected edges      : %d' % ne)
    print('edges used once       : %d   (watertight closed surface must be 0)' % once)
    print('edges used >2         : %d' % over)
    print('wrote %s' % args.out)


if __name__ == '__main__':
    main()
