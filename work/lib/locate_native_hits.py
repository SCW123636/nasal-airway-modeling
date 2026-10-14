"""Where do the native self-intersection points actually sit?

surfaceCheck reports points, not face pairs. For each case this locates every
reported point on the surface: nearest wall triangle, distance, and whether the
point sits on an opening cap instead of the airway wall.

A point that lands on an opening cap means the opening rim, not the airway, is
generating the report -- a completely different fix than a defect in the wall.
"""
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_compare import parse_stl_regions, build_topology

NATIVE = Path('D:/项目/鼻腔建模/.tools/sliver-repair-20261011/native2')
STL = {
    'p2_source': Path('D:/项目/鼻腔建模/.tools/surface-preflight-20261008-r10/p2_source/combined.stl'),
    'p2_repaired': Path('D:/项目/鼻腔建模/.tools/sliver-repair-20261011/p2/combined_repaired.stl'),
    'p3t1_source': Path('D:/项目/鼻腔建模/.tools/surface-preflight-20261008-r10/p3t1_source/combined.stl'),
    'p3t1_repaired': Path('D:/项目/鼻腔建模/.tools/sliver-repair-20261011/p3t1/combined_repaired.stl'),
}


def read_points(path):
    pts = []
    for line in path.read_text().splitlines():
        if line.startswith('v '):
            pts.append([float(x) for x in line.split()[1:4]])
    return np.asarray(pts, float)


def main():
    for case, stl in STL.items():
        tris, labels = parse_stl_regions(stl)
        verts, faces = build_topology(np.array(tris, dtype=np.float64))
        tris = faces
        labels = np.asarray(labels, object)
        centres = verts[tris].mean(axis=1)
        tree = cKDTree(centres)
        pts = read_points(NATIVE / case / 'selfInterPoints.obj')
        d, i = tree.query(pts)
        from collections import Counter
        c = Counter(labels[i])
        print('=' * 18, case)
        print(f'   points={len(pts)}  nearest-triangle dist m: max={d.max():.3e} '
              f'median={np.median(d):.3e}  >1e-6m: {(d > 1e-6).sum()}')
        for k, v in c.most_common():
            print(f'   patch {k:20s} {v:4d}  ({100*v/len(pts):.1f}%)')
        # are the hit points clustered?
        from scipy.sparse.csgraph import connected_components
        from scipy.sparse import coo_matrix
        r = 2e-3
        # are the hit points clustered? Link two hit points that fall within 2 mm of
        # each other, measured directly between hit points rather than through
        # the surface triangles.
        hp = cKDTree(pts)
        pairs = hp.query_ball_point(pts, r)
        rows, cols = [], []
        for k, lst in enumerate(pairs):
            for j in lst:
                if j > k:
                    rows.append(k)
                    cols.append(j)
        g = coo_matrix((np.ones(len(rows)), (rows, cols)),
                       shape=(len(pts), len(pts)))
        _, lab = connected_components(g + g.T, directed=False)
        sizes = np.bincount(lab)
        print(f'   clusters @2mm: {len(sizes)}  largest={sizes.max()}  '
              f'singletons={(sizes == 1).sum()}')


if __name__ == '__main__':
    main()