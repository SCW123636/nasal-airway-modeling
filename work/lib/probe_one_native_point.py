# -*- coding: utf-8 -*-
"""Focused, brute-force cross-check of one native self-intersection point.

Validates the KD-tree candidate bound used by remeasure_native_hit_distance.py and
shows WHY the old adjudicate_native_hits.py counted 2-20 "on surface" triangles:
its interior-projection branch returns |n|*clip(n.ap/|n|^2, 0, 1), a quantity with
units of m^2 (numerically ~2x triangle area).  Comparing that against a 1e-9 *m*
threshold makes every sufficiently thin triangle count as "on surface".
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_compare import parse_stl_regions, build_topology  # noqa: E402
from remeasure_native_hit_distance import closest_point_on_triangles  # noqa: E402

CASE = sys.argv[1] if len(sys.argv) > 1 else 'p2_source'
IDX = int(sys.argv[2]) if len(sys.argv) > 2 else 0

STL = {
    'p2_source': Path('D:/项目/鼻腔建模/.tools/surface-preflight-20261008-r10/p2_source/combined.stl'),
    'p2_repaired': Path('D:/项目/鼻腔建模/.tools/sliver-repair-20261011/p2/combined_repaired.stl'),
    'p3t1_source': Path('D:/项目/鼻腔建模/.tools/surface-preflight-20261008-r10/p3t1_source/combined.stl'),
    'p3t1_repaired': Path('D:/项目/鼻腔建模/.tools/sliver-repair-20261011/p3t1/combined_repaired.stl'),
}[CASE]
OBJ = Path('D:/项目/鼻腔建模/.tools/sliver-repair-20261011/native2') / CASE / 'selfInterPoints.obj'

pts = []
for line in OBJ.read_text(encoding='utf-8', errors='replace').splitlines():
    if line.startswith('v '):
        pts.append([float(x) for x in line.split()[1:4]])
P = np.asarray(pts, float)
p = P[IDX:IDX + 1]
print(f'case={CASE} point #{IDX} of {len(P)}: {p[0]}')

tris, labels = parse_stl_regions(STL)
verts, faces = build_topology(np.array(tris, dtype=np.float64))
labels = np.asarray(labels, object)
A = verts[faces[:, 0]]
B = verts[faces[:, 1]]
C = verts[faces[:, 2]]
areas = 0.5 * np.linalg.norm(np.cross(B - A, C - A), axis=1)
print(f'triangles={len(faces)}  area: min={areas.min():.3e} median={np.median(areas):.3e} m^2')

# ---- brute force over ALL triangles (no candidate filtering) ----
_, D = closest_point_on_triangles(p, A, B, C)
D = D[0]
order = np.argsort(D)
print('\n-- brute force, 12 nearest triangles (exact point-triangle distance) --')
for j in order[:12]:
    f = faces[j]
    print(f'   tri {j:7d} d={D[j]:.3e} m  area={areas[j]:.3e} m^2  '
          f'patch={labels[j]:20s} verts={[int(x) for x in f]}')

# ---- the old adjudicate metric on the same neighbourhood ----
ab = B - A
ac = C - A
ap = p[:, None, :] - A[None, :, :]
n = np.cross(ab, ac)
nn = np.einsum('mk,mk->m', n, n)
nn = np.where(nn > 0, nn, 1.0)
t = np.clip(np.einsum('mk,nmk->nm', n, ap) / nn, 0.0, 1.0)
d_plane_old = np.linalg.norm(n[None, :, :] * t[:, :, None], axis=-1)[0]
cnt_old = int((d_plane_old <= 1e-9).sum())
cnt_new = int((D <= 1e-9).sum())
print(f'\n-- metric comparison on this point --')
print(f'   old adjudicate interior-branch value <= 1e-9 : {cnt_old} triangles')
print(f'   correct point-triangle distance   <= 1e-9 : {cnt_new} triangles')
thin = int(((d_plane_old <= 1e-9) & (areas > 1e-9)).sum())
print(f'   ...of which have area > 1e-9 m^2 (i.e. not actually thin): {thin}')
print(f'   area of triangles the old metric calls "on surface": '
      f'{[f"{areas[j]:.1e}" for j in np.where(d_plane_old <= 1e-9)[0][:8]]}')

# ---- adjacency among the true nearest triangles ----
near = order[:12]
for i in range(len(near)):
    for j in range(i + 1, len(near)):
        if D[near[i]] <= 1e-6 and D[near[j]] <= 1e-6:
            shared = set(int(v) for v in faces[near[i]]) & set(int(v) for v in faces[near[j]])
            print(f'   pair ({near[i]},{near[j]}) d=({D[near[i]]:.2e},{D[near[j]]:.2e}) '
                  f'shared_verts={len(shared)} -> {"adjacent" if shared else "NON-adjacent"}')
