"""T-011 diagnostic: triangle-quality statistics of a (closed) ASCII STL surface.

Why: netgen derives its local element size from the local STL edge lengths, so a
handful of *sliver* triangles (near-zero edges) can drive runaway local
refinement. This measures min/median edge, degenerate-triangle count and aspect
ratio so two surfaces can be compared on the property that actually controls
netgen memory, instead of on the raw triangle count.

Usage: python3 inspect_stl.py <surface.stl>
"""
import sys
import numpy as np


def load(path):
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


def stats(path):
    T = load(path)
    V = T.reshape(-1, 3)
    e = np.linalg.norm(np.stack([T[:, 1] - T[:, 0], T[:, 2] - T[:, 1],
                                 T[:, 0] - T[:, 2]], axis=1), axis=2)
    u, v = T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]
    area = 0.5 * np.linalg.norm(np.cross(u, v), axis=1)
    emin, emax = e.min(axis=1), e.max(axis=1)
    uv = np.unique(np.round(V / 1e-6).astype(np.int64), axis=0)
    print('FILE', path)
    print('  triangles %d  unique_verts %d  V/T %.3f' % (len(T), len(uv), len(uv) / len(T)))
    print('  edge     min %.6f  p1 %.6f  median %.4f  max %.4f'
          % (e.min(), np.percentile(e, 1), np.median(e), e.max()))
    print('  tri_emin min %.6f  median %.4f' % (emin.min(), np.median(emin)))
    print('  area     min %.3e  p1 %.3e  median %.4f  max %.4f'
          % (area.min(), np.percentile(area, 1), np.median(area), area.max()))
    print('  degenerate area<1e-9 : %d   <1e-6: %d'
          % (int((area < 1e-9).sum()), int((area < 1e-6).sum())))
    print('  sliver emin<0.01mm : %d   <0.05mm: %d   <0.1mm: %d'
          % (int((emin < 0.01).sum()), int((emin < 0.05).sum()), int((emin < 0.1).sum())))
    ar = emax / np.maximum(emin, 1e-9)
    print('  aspect emax/emin  p99 %.1f  max %.1f' % (np.percentile(ar, 99), ar.max()))
    print('  bbox', np.round(V.min(axis=0), 2), np.round(V.max(axis=0), 2))


if __name__ == '__main__':
    stats(sys.argv[1])
