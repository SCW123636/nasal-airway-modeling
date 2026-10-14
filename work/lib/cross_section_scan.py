"""Cross-section area as the placement criterion (mask-free version).

components_reached was measured and rejected as a criterion: the reviewed
planes sit at 3-6 reached components while positions far from the airway
trivially give 1, so minimising it would push the plane 20 mm away.

The quantity that defines an opening is the area of the airway lumen
cross-section at the plane, which is exactly the area of the cap that
clip_and_cap will create there. So it is computed here the same way the
production cap is: intersect the plane with the wall triangles.

Two facts forced this rewrite (both measured, not assumed):

1. A marching cubes grid has NO vertex within 1e-7 mm of an arbitrary plane
   (verified: zero at that tolerance, and zero at 1e-3) while 241-865
   triangles straddle it. The section must therefore be built from
   edge/plane intersections, never from projected vertices.
2. Restricting the section to the connectivity selection breaks the contour
   (exactly one degree-1 node at the reviewed position, every case) and makes
   inward shifts fail with 'no negative-side seed'. Neither is a property of
   the geometry - both are artefacts of filtering by a mask that exists for a
   different purpose. The source surfaces are closed manifolds, so the
   unfiltered section closes on its own.

Evaluated at the reviewed position and at a sweep of offsets, so the criterion
must reproduce five hand-reviewed positions before it runs unattended.
"""
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import vtk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_reviewed_surface_drafts import load_adopted
from ct_case_pipeline import CaseManager
from medical_review import MedicalReviewStore
from export_candidate_preview import triangle_arrays

SRC = Path('C:/ts_work/reviewed_surface_drafts_20261008_r3')
OPENINGS = ('nostril_L', 'nostril_R', 'nasopharynx_outlet')
SHIFT_MM = (-24, -16, -12, -8, -6, -4, -3, -2, -1, 0, 1, 2, 3, 4, 6, 8, 12, 16, 24)


def plane_basis(normal):
    n = np.asarray(normal, float)
    n = n / np.linalg.norm(n)
    helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(n, helper)
    u /= np.linalg.norm(u)
    return n, u, np.cross(n, u)


def section_loops_detail(points, faces, origin, normal):
    """Return (areas_mm2, n_loops, diag, detail) for the plane cut.

    detail carries what section_loops used to throw away, because seeding the
    connectivity flood needs it:

      cut_points_3d    (K,3) welded intersection points in true 3D. Note the
                       area maths below works on the 2D projection (P[:,1:3]);
                       these are the same nodes in space, which is what a rim
                       band seed has to be derived from.
      loops            list of index arrays into cut_points_3d, one per closed
                       contour, in the same order as the returned areas.
      loop_areas_mm2   the areas again, aligned with loops.
      adjacency        welded-node adjacency, for callers that want to walk the
                       rim themselves.

    The area computation is byte-for-byte the code that used to live in
    section_loops; the wrapper now delegates here, so the recorded baselines
    (正常路径基本方法_v1.md section 5) cannot drift.
    """
    n, u, v = plane_basis(normal)
    o = np.asarray(origin, float)
    s = (points - o) @ n
    tv = s[faces]
    strad = np.any(tv > 0, axis=1) & np.any(tv < 0, axis=1)
    fs = faces[strad]
    diag = {'straddling_triangles': int(strad.sum())}
    if not len(fs):
        diag['open_nodes'] = 0
        return [], 0, diag, _empty_detail()

    cuts = []
    cut_face = []
    strad_idx = np.where(strad)[0]
    for fi, f in enumerate(fs):
        pts2 = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            ia, ib = int(f[a]), int(f[b])
            sa, sb = s[ia], s[ib]
            if (sa > 0) == (sb > 0):
                continue
            t = sa / (sa - sb)
            pts2.append(points[ia] + t * (points[ib] - points[ia]))
        if len(pts2) == 2:
            cuts.append(pts2)
            cut_face.append(int(strad_idx[fi]))   # index into the caller's faces
    diag['cut_segments'] = len(cuts)
    if not cuts:
        diag['open_nodes'] = 0
        return [], 0, diag, _empty_detail()

    cuts = np.asarray(cuts)                      # (M, 2, 3)
    # Weld: every straddling triangle produced its own two copies of the cut
    # points, so without deduplication every node has degree 1 and no contour
    # can ever close. Welding on the 2D projection at a tolerance well below
    # the 0.2-0.35 mm grid pitch is safe and is what makes the loop structure
    # meaningful.
    n_, u_, v_ = plane_basis(normal)
    raw3 = cuts.reshape(-1, 3)
    proj_all = np.stack((raw3 @ u_, raw3 @ v_), axis=1)
    uniq, inverse = np.unique(np.round(proj_all, 6), axis=0, return_inverse=True)
    inverse = inverse.ravel()
    P = np.zeros((len(uniq), 3))
    P[:, 1] = uniq[:, 0]
    P[:, 2] = uniq[:, 1]
    # true 3D position of each welded node: the first raw point that mapped to it
    first_idx = np.unique(inverse, return_index=True)[1]
    P3 = raw3[first_idx]
    diag['cut_points_raw'] = len(proj_all)
    diag['cut_points_welded'] = len(uniq)

    adj = defaultdict(set)
    for k in range(len(cuts)):
        a, b = int(inverse[2 * k]), int(inverse[2 * k + 1])
        if a == b:
            continue
        adj[a].add(b)
        adj[b].add(a)
    degs = np.array([len(adj[i]) for i in range(len(P))])
    diag['degree_histogram'] = {int(d): int((degs == d).sum()) for d in np.unique(degs)}
    open_nodes = int((degs < 2).sum())

    proj = np.stack((P[:, 1], P[:, 2]), axis=1)
    seen = np.zeros(len(P), bool)
    areas = []
    loops = []
    for start in range(len(P)):
        if seen[start]:
            continue
        loop, cur, prev = [], start, -1
        while cur >= 0 and not seen[cur]:
            seen[cur] = True
            loop.append(cur)
            nxt = [x for x in adj[cur] if x != prev]
            prev, cur = cur, (nxt[0] if nxt else -1)
        if len(loop) >= 3:
            xy = proj[np.array(loop)]
            areas.append(abs(0.5 * (np.dot(xy[:, 0], np.roll(xy[:, 1], -1))
                                    - np.dot(xy[:, 1], np.roll(xy[:, 0], -1)))))
            loops.append(np.asarray(loop, dtype=np.int64))
    diag['open_nodes'] = open_nodes
    detail = {
        'cut_points_3d': P3,
        'loops': loops,
        'loop_areas_mm2': list(areas),
        'adjacency': {i: sorted(adj[i]) for i in range(len(P))},
        # which straddling triangle produced each cut segment, and which
        # straddling triangles each loop came from. The second map is what lets
        # a caller seed from the rim of one chosen loop instead of every
        # triangle that happens to cross the plane.
        'cut_face_index': np.asarray(cut_face, dtype=np.int64),
        'loop_faces': [np.asarray(sorted({int(cut_face[k]) for k in range(len(cuts))
                                          if inverse[2 * k] in set(idx.tolist())
                                          or inverse[2 * k + 1] in set(idx.tolist())}),
                                dtype=np.int64) for idx in loops],
    }
    return areas, len(areas), diag, detail


def _empty_detail():
    return {'cut_points_3d': np.zeros((0, 3)), 'loops': [],
            'loop_areas_mm2': [], 'adjacency': {}}


def section_loops(points, faces, origin, normal):
    """Return (areas_mm2, n_loops, diag) for the plane cut of the closed wall.

    Thin wrapper over section_loops_detail, kept so existing callers keep their
    three-tuple contract and their numbers.
    """
    areas, n_loops, diag, _detail = section_loops_detail(points, faces, origin, normal)
    return areas, n_loops, diag


def main():
    work = Path(__file__).resolve().parents[1]
    mgr = CaseManager(Path('C:/ts_work/project_cases'))
    store = MedicalReviewStore(mgr, work / '06_auto_landmarks')
    try:
        for case in ('p0', 'p1', 'p2', 'p3', 'p3t1'):
            config, _ = load_adopted(store, case)
            reader = vtk.vtkXMLPolyDataReader()
            reader.SetFileName(str(SRC / case / 'source_surface.vtp'))
            reader.Update()
            points, faces = triangle_arrays(reader.GetOutput())
            print('=' * 26, case)
            for name in OPENINGS:
                spec = config['planes_lps'][name]
                n, _, _ = plane_basis(spec['normal_lps'])
                o = np.asarray(spec['point_lps_mm'], float)
                cells = []
                for d in SHIFT_MM:
                    areas, nloops, diag = section_loops(points, faces, o + d * n, spec['normal_lps'])
                    total = sum(areas)
                    mark = '' if diag['open_nodes'] == 0 else '!'
                    cells.append((d, f'{total:.0f}/{nloops}{mark}' if areas else 'none'))
                print(f'   {name:18s} ' + ' '.join(f'{d:+d}:{a}' for d, a in cells))
    finally:
        mgr.pool.shutdown(wait=True)


if __name__ == '__main__':
    main()