# -*- coding: utf-8 -*-
"""
Adjudicate OpenFOAM `surfaceCheck -checkSelfIntersection` reported points.

Idea: a reported point is a GENUINE self-intersection point only if it lies on
>= 2 mutually NON-ADJACENT triangles (distance ~ 0 to both, and inside both).
If it lies on exactly one triangle, the "intersection" is a phantom.

This test is deliberately independent of the Moller-Trumbore determinant, so it
also covers the near-coplanar / coplanar case that MT silently skips (|det| < eps).
"""
import sys, json, argparse
import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, __file__.rsplit('\\', 1)[0])
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from decide_selfintersection_precision import parse_stl, build_topology


def read_obj_points(path):
    pts = []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith('v '):
                pts.append([float(x) for x in line.split()[1:4]])
    return np.array(pts, dtype=np.float64)


def point_triangle_dist(P, A, B, C):
    """Vectorised point-triangle distance (Ericson). P:(N,3) A/B/C:(M,3) -> (N,M)."""
    # broadcast to (N,M,3)
    p = P[:, None, :]
    a = A[None, :, :]; b = B[None, :, :]; c = C[None, :, :]
    ab = b - a; ac = c - a; ap = p - a
    d1 = np.einsum('nmk,nmk->nm', ab, ap)
    d2 = np.einsum('nmk,nmk->nm', ac, ap)
    in_a = (d1 <= 0) & (d2 <= 0)
    bp = p - b
    d3 = np.einsum('nmk,nmk->nm', ab, bp)
    d4 = np.einsum('nmk,nmk->nm', ac, bp)
    in_b = (d3 >= 0) & (d4 <= d3)
    cp = p - c
    d5 = np.einsum('nmk,nmk->nm', ab, cp)
    d6 = np.einsum('nmk,nmk->nm', ac, cp)
    in_c = (d6 >= 0) & (d5 <= d6)
    vc = d1 * d4 - d3 * d2
    in_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    in_bc = (d3 * d6 - d5 * d4 <= 0) & (d3 >= 0) & (d5 >= 0)
    in_ca = (d5 * d2 - d1 * d6 <= 0) & (d5 <= 0) & (d1 >= 0)

    n = np.cross(ab, ac)
    nn = np.einsum('nmk,nmk->nm', n, n)
    nn = np.where(nn > 0, nn, 1.0)

    def pt_dist(Q):
        v = p - Q
        return np.sqrt(np.einsum('nmk,nmk->nm', v, v))

    t = np.clip(np.einsum('nmk,nmk->nm', n, ap) / nn, 0.0, 1.0)
    proj = p - n * t[:, :, None]
    d_plane = np.sqrt(np.einsum('nmk,nmk->nm', p - proj, p - proj))

    def seg_dist(X, Y):
        u = Y - X
        w = p - X
        uu = np.einsum('nmk,nmk->nm', u, u)
        uu = np.where(uu > 0, uu, 1.0)
        s = np.clip(np.einsum('nmk,nmk->nm', w, u) / uu, 0.0, 1.0)
        q = X + u * s[:, :, None]
        v = p - q
        return np.sqrt(np.einsum('nmk,nmk->nm', v, v))

    dist = np.where(in_a, pt_dist(a),
           np.where(in_b, pt_dist(b),
           np.where(in_c, pt_dist(c),
           np.where(in_ab, seg_dist(a, b),
           np.where(in_bc, seg_dist(b, c),
           np.where(in_ca, seg_dist(c, a), d_plane))))))
    return dist


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stl', required=True)
    ap.add_argument('--points', required=True)
    ap.add_argument('--on-surface-m', type=float, default=1e-9,
                    help='distance below which the point is considered ON a triangle')
    ap.add_argument('--radius-mm', type=float, default=1.0)
    ap.add_argument('--output', default=None)
    args = ap.parse_args()

    P = read_obj_points(args.points)
    tris = parse_stl(args.stl)
    verts, faces = build_topology(tris)
    cent = verts[faces].mean(axis=1)
    rad = np.linalg.norm(verts[faces] - cent[:, None, :], axis=2).max(axis=1)
    rmax = float(rad.max())
    tree = cKDTree(cent)
    R = args.radius_mm * 1e-3

    genuine = 0
    phantom = 0
    off_surface = 0
    details = []
    for i in range(len(P)):
        p = P[i:i + 1]
        nb = np.asarray(tree.query_ball_point(p, R + rmax)[0], dtype=np.int64)
        if nb.size == 0:
            off_surface += 1
            details.append({"i": i, "verdict": "no_triangle_nearby"})
            continue
        A = verts[faces[nb][:, 0]]; B = verts[faces[nb][:, 1]]; C = verts[faces[nb][:, 2]]
        d = point_triangle_dist(p, A, B, C)[0]
        order = np.argsort(d)
        on = nb[d <= args.on_surface_m]
        # group candidates: keep the closest few triangles
        near = nb[order[:6]]
        d_near = d[order[:6]]
        # non-adjacency among the triangles the point lies on
        adj = {}
        exact = nb[d <= 1e-12]
        # fall back: use the two closest triangles
        if len(exact) < 2:
            pair = near[:2]
        else:
            pair = exact[:2]
        if len(pair) < 2:
            verdict = "single_triangle"
            phantom += 1
        else:
            f0 = faces[pair[0]]; f1 = faces[pair[1]]
            shared = bool(set(int(x) for x in f0) & set(int(x) for x in f1))
            if shared:
                verdict = "adjacent_only"
                phantom += 1
            else:
                verdict = "two_nonadjacent"
                genuine += 1
        details.append({
            "i": i,
            "point": [float(x) for x in P[i]],
            "verdict": verdict,
            "dist_to_closest_tri_m": float(d_near[0]),
            "dist_to_second_tri_m": float(d_near[1]) if len(d_near) > 1 else None,
            "n_tris_within_on_surface": int(len(on)),
            "closest_tris": [int(x) for x in near[:3]],
        })

    print(f"[reported points]  {len(P)}")
    print(f"[genuine  ] two non-adjacent triangles through the point : {genuine}")
    print(f"[phantom  ] only one / only adjacent triangles           : {phantom}")
    print(f"[off      ] no triangle nearby                           : {off_surface}")
    ds = [d for d in details if d.get("dist_to_closest_tri_m") is not None]
    if ds:
        arr = np.array([d["dist_to_closest_tri_m"] for d in ds])
        print(f"[dist to closest triangle] min={arr.min():.3e} m  median={np.median(arr):.3e}  max={arr.max():.3e}")
        arr2 = np.array([d["dist_to_second_tri_m"] for d in ds if d["dist_to_second_tri_m"] is not None])
        if arr2.size:
            print(f"[dist to 2nd triangle    ] min={arr2.min():.3e} m  median={np.median(arr2):.3e}  max={arr2.max():.3e}")

    res = {
        "stl": args.stl, "points": args.points, "reported": int(len(P)),
        "genuine_two_nonadjacent": int(genuine),
        "phantom_single_or_adjacent": int(phantom),
        "no_triangle_nearby": int(off_surface),
        "on_surface_m": args.on_surface_m,
        "details": details,
    }
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(res, f, indent=2)
    return res


if __name__ == '__main__':
    main()
