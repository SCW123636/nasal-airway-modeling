# -*- coding: utf-8 -*-
"""How far are the native surfaceCheck self-intersection points from the surface?

Why this script exists
----------------------
`locate_native_hits.py` measured the distance from each reported point to the
nearest triangle CENTROID.  The centroid is a point OF the triangle, so
centroid-distance is only an *upper bound* on the true triangle distance: a
point lying exactly ON a triangle still measures roughly the triangle inradius
away (0.1-0.2 mm at this mesh scale).  The figure quoted in
`work/07_cfd_pipeline/自相交定性结论_20261011.md` §5.3 ("1.7-1.9e-4 m, all > 1e-6 m")
therefore cannot support the inference that was drawn from it.

This script measures the true point-to-triangle distance (Ericson closest point
on triangle, chunked float64) and reports, per case:
  * real minimum distance from each reported point to any triangle
  * how many triangles the point lies on (<= 1e-9 m) and whether two of them are
    mutually NON-adjacent  ->  the genuine-intersection test, with a correct distance
  * the old centroid distance, for comparison

Everything is printed and written to JSON; nothing is inferred from stdout alone.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_compare import parse_stl_regions, build_topology  # noqa: E402

CASES = {
    'p2_source': Path('D:/项目/鼻腔建模/.tools/surface-preflight-20261008-r10/p2_source/combined.stl'),
    'p2_repaired': Path('D:/项目/鼻腔建模/.tools/sliver-repair-20261011/p2/combined_repaired.stl'),
    'p3t1_source': Path('D:/项目/鼻腔建模/.tools/surface-preflight-20261008-r10/p3t1_source/combined.stl'),
    'p3t1_repaired': Path('D:/项目/鼻腔建模/.tools/sliver-repair-20261011/p3t1/combined_repaired.stl'),
}
NATIVE = Path('D:/项目/鼻腔建模/.tools/sliver-repair-20261011/native2')


def read_obj_points(path):
    pts = []
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        if line.startswith('v '):
            pts.append([float(x) for x in line.split()[1:4]])
    return np.asarray(pts, float)


def closest_point_on_triangles(P, A, B, C):
    """Ericson closest-point-on-triangle, vectorised.

    P:(N,3) query points; A,B,C:(M,3) triangle corners -> Q:(N,M,3) closest
    points and D:(N,M) distances.
    """
    ab = B - A                                    # (M,3)
    ac = C - A                                    # (M,3)
    ap = P[:, None, :] - A[None, :, :]            # (N,M,3)
    d1 = np.einsum('nmk,mk->nm', ap, ab)
    d2 = np.einsum('nmk,mk->nm', ap, ac)
    bp = P[:, None, :] - B[None, :, :]
    d3 = np.einsum('nmk,mk->nm', bp, ab)
    d4 = np.einsum('nmk,mk->nm', bp, ac)
    cp = P[:, None, :] - C[None, :, :]
    d5 = np.einsum('nmk,mk->nm', cp, ab)
    d6 = np.einsum('nmk,mk->nm', cp, ac)

    vc = d1 * d4 - d3 * d2
    vb = d5 * d2 - d1 * d6
    va = d3 * d6 - d5 * d4
    denom = va + vb + vc
    safe = np.where(np.abs(denom) > 0, denom, 1.0)
    v = np.clip(vb / safe, 0.0, 1.0)
    w = np.clip(vc / safe, 0.0, 1.0)
    Q = A[None, :, :] + ab[None, :, :] * v[:, :, None] + ac[None, :, :] * w[:, :, None]

    def put(mask, target):
        # target is either (M,3) corner or an already-broadcast (N,M,3) array
        t = target[None, :, :] if target.ndim == 2 else target
        return np.where(mask[:, :, None], t, Q)

    # vertex regions
    Q = put((d1 <= 0) & (d2 <= 0), A)
    Q = put((d3 >= 0) & (d4 <= d3), B)
    Q = put((d6 >= 0) & (d5 <= d6), C)
    # edge AB
    m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    den = d1 - d3
    t = np.where(m & (den != 0), d1 / np.where(den != 0, den, 1.0), 0.0)
    Q = put(m, A + ab * t[:, :, None])
    # edge AC
    m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    den = d2 - d6
    t = np.where(m & (den != 0), d2 / np.where(den != 0, den, 1.0), 0.0)
    Q = put(m, A + ac * t[:, :, None])
    # edge BC
    m = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    den = (d4 - d3) + (d5 - d6)
    t = np.where(m & (den != 0), (d4 - d3) / np.where(den != 0, den, 1.0), 0.0)
    Q = put(m, B + (C - B) * t[:, :, None])

    D = np.linalg.norm(P[:, None, :] - Q, axis=-1)
    return Q, D


def self_test():
    A = np.array([[0.0, 0.0, 0.0]])
    B = np.array([[1.0, 0.0, 0.0]])
    C = np.array([[0.0, 1.0, 0.0]])
    tests = [
        ([0.25, 0.25, 0.0], 0.0),
        ([0.25, 0.25, 1.0], 1.0),
        ([0.25, 0.25, 0.1], 0.1),
        ([2.0, 0.0, 0.0], 1.0),
        ([-1.0, -1.0, 0.0], np.sqrt(2.0)),
        ([0.5, -1.0, 0.0], 1.0),
        ([0.0, 0.0, 0.0], 0.0),
        ([1.0, 1.0, 0.0], np.sqrt(0.5)),   # closest point is the hypotenuse midpoint
    ]
    P = np.array([t[0] for t in tests])
    _, D = closest_point_on_triangles(P, A, B, C)
    ok = True
    for (p, want), got in zip(tests, D[:, 0]):
        good = abs(got - want) < 1e-12
        ok &= good
        print(f'  selftest p={p}  want={want:.6g}  got={got:.6g}  {"OK" if good else "FAIL"}')
    return ok


def measure(case, stl, pts):
    """Exact minimum point-to-triangle distance, via a centroid KD-tree bound.

    For any triangle T with centroid distance d_c:  dist(P,T) >= d_c - r_T >= d_c - rmax
    (r_T = circumradius of T), while dist(P,T) <= d_c because the centroid lies on T.
    Hence the argmin is inside the ball {d_c <= max(d_c_min, 1e-6) + rmax}; every
    triangle outside that ball is provably not the closest one.  Exact, not approximate.
    """
    from scipy.spatial import cKDTree

    tris, labels = parse_stl_regions(stl)
    verts, faces = build_topology(np.array(tris, dtype=np.float64))
    labels = np.asarray(labels, object)
    A = verts[faces[:, 0]]
    B = verts[faces[:, 1]]
    C = verts[faces[:, 2]]
    centres = verts[faces].mean(axis=1)
    rmax = float(np.linalg.norm(verts[faces] - centres[:, None, :], axis=2).max())

    tree = cKDTree(centres)
    dcent, _ = tree.query(pts)          # the old (invalid) metric, kept for comparison

    rows = []
    dmin = np.full(len(pts), np.nan)
    for i in range(len(pts)):
        # candidate ball: guaranteed to contain the closest triangle and every
        # triangle within 1e-6 m of the point
        R = max(float(dcent[i]), 1e-6) + rmax
        cand = np.asarray(tree.query_ball_point(pts[i], R), dtype=np.int64)
        if cand.size == 0:
            cand = np.array([int(np.argmin(dcent))])
        _, D = closest_point_on_triangles(pts[i:i + 1], A[cand], B[cand], C[cand])
        D = D[0]
        j = int(np.argmin(D))
        dmin[i] = D[j]
        on9 = cand[D <= 1e-9]
        on6 = cand[D <= 1e-6]
        two_nonadj = False
        for x in range(len(on9)):
            for y in range(x + 1, len(on9)):
                if not (set(int(v) for v in faces[on9[x]])
                        & set(int(v) for v in faces[on9[y]])):
                    two_nonadj = True
                    break
            if two_nonadj:
                break
        rows.append({
            'i': int(i),
            'dist_min_m': float(D[j]),
            'dist_to_nearest_centroid_m': float(dcent[i]),
            'n_tri_within_1e-9': int(len(on9)),
            'n_tri_within_1e-6': int(len(on6)),
            'two_nonadjacent_within_1e-9': bool(two_nonadj),
            'closest_tri': int(cand[j]),
            'closest_patch': str(labels[cand[j]]),
        })

    argmin = np.array([r['closest_tri'] for r in rows])
    n_tri = int(len(faces))

    return {
        'case': case,
        'stl': str(stl),
        'n_reported_points': int(len(pts)),
        'n_triangles': int(n_tri),
        'dist_min_m': {'min': float(dmin.min()), 'median': float(np.median(dmin)),
                       'max': float(dmin.max())},
        'dist_centroid_m': {'min': float(dcent.min()), 'median': float(np.median(dcent)),
                            'max': float(dcent.max())},
        'n_points_on_surface_1e-9': int((dmin <= 1e-9).sum()),
        'n_points_on_surface_1e-6': int((dmin <= 1e-6).sum()),
        'n_points_two_nonadjacent_1e-9': int(sum(r['two_nonadjacent_within_1e-9'] for r in rows)),
        'rows': rows,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='D:/项目/鼻腔建模/.tools/native_distance_remeasure_20261012/summary.json')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()

    if args.selftest:
        ok = self_test()
        print('selftest:', 'PASS' if ok else 'FAIL')
        return 0 if ok else 1

    out = []
    for case, stl in CASES.items():
        obj = NATIVE / case / 'selfInterPoints.obj'
        if not stl.exists() or not obj.exists():
            print(f'{case}: missing input ({stl.exists()=} {obj.exists()=}) -> skip')
            continue
        pts = read_obj_points(obj)
        r = measure(case, stl, pts)
        out.append({k: v for k, v in r.items() if k != 'rows'})
        print(f"== {case}: points={r['n_reported_points']} tris={r['n_triangles']}")
        print(f"   TRUE dist to nearest triangle  : min={r['dist_min_m']['min']:.3e} "
              f"median={r['dist_min_m']['median']:.3e} max={r['dist_min_m']['max']:.3e} m")
        print(f"   OLD centroid dist (invalid)    : median={r['dist_centroid_m']['median']:.3e} m")
        print(f"   on surface (<=1e-9): {r['n_points_on_surface_1e-9']}/{r['n_reported_points']}"
              f"   (<=1e-6): {r['n_points_on_surface_1e-6']}/{r['n_reported_points']}")
        print(f"   >=2 NON-adjacent tris within 1e-9: {r['n_points_two_nonadjacent_1e-9']}"
              f"/{r['n_reported_points']}")
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(Path(args.out).with_name(f'{case}.json'), 'w', encoding='utf-8') as f:
            json.dump(r, f, indent=1)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f'\nwritten: {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
