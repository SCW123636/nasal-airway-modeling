# -*- coding: utf-8 -*-
"""
Exact triangle-triangle intersection with a DIMENSIONLESS degeneracy test.

Why this file exists (post-mortem of a real bug):
    The earlier kernel used `valid = abs(det) >= eps` with eps = 1e-9. `det` is
    -d . (e1 x e2), i.e. length * area, units m^3. On this mesh a genuine transverse
    intersection gives |det| ~ 1e-10 .. 1e-11 (edge 4.6e-4 m times 2*area 1.8e-7 m^2),
    so an absolute 1e-9 threshold silently rejected nearly every real intersection and
    produced the false conclusion "surface has no genuine self-intersections".
    Here the test is made dimensionless: |det| >= eps_rel * |d| * |n|, eps_rel ~ 1e-12.

Coplanar pairs are handled separately (2D projection + 2D overlap / touch test),
because for them det == 0 exactly and no edge-triangle test can ever fire.

Returned kinds:
    0 none
    1 transverse   (an edge of one triangle passes through the other)
    2 coplanar_overlap (coplanar AND the 2D triangles overlap with positive area)
    3 coplanar_touch   (coplanar but only edge/vertex contact, no area overlap)
"""
import numpy as np

E = {
    "eps_rel": 1e-12,     # dimensionless: |det| / (|d| |n|)
    "eps_uv": 1e-9,       # dimensionless: tolerance on t, u, v in [0,1]
    "eps_cop_sin": 1e-8,  # |sin(angle between normals)| -> coplanar if below
    "eps_cop_sep_m": 1e-7,  # plane separation (m) -> coplanar if below
    "eps_2d": 1e-12,      # 2D orientation tolerance (relative, on normalised coords)
}


def _seg_tri_norm(A, B, P0, P1, P2, eps_rel=E["eps_rel"], eps_uv=E["eps_uv"]):
    """Vectorised segment(A,B) vs triangle(P0,P1,P2). Dimensionless degeneracy test."""
    e1 = P1 - P0
    e2 = P2 - P0
    d = B - A
    n = np.cross(e1, e2)
    nlen = np.linalg.norm(n, axis=1)
    dlen = np.linalg.norm(d, axis=1)
    det = -np.einsum('ij,ij->i', d, n)
    scale = dlen * nlen
    valid = np.abs(det) >= eps_rel * np.where(scale > 0, scale, 1.0)
    inv = np.where(valid, 1.0 / np.where(valid, det, 1.0), 0.0)
    ao = A - P0
    t = np.einsum('ij,ij->i', ao, n) * inv
    u = np.einsum('ij,ij->i', ao, np.cross(d, e2)) * inv
    v = np.einsum('ij,ij->i', ao, np.cross(e1, d)) * inv
    hit = (valid & (t >= -eps_uv) & (t <= 1.0 + eps_uv) &
           (u >= -eps_uv) & (v >= -eps_uv) & ((u + v) <= 1.0 + eps_uv))
    return hit


def _face_vs_face_transverse(A, B):
    """6 edge-vs-triangle tests between triangle pair A,B of shape (N,3,3)."""
    n = A.shape[0]
    la = np.concatenate([A[:, 0], A[:, 1], A[:, 2]], axis=0)
    lb = np.concatenate([A[:, 1], A[:, 2], A[:, 0]], axis=0)
    Tb = np.repeat(B, 3, axis=0)
    h1 = _seg_tri_norm(la, lb, Tb[:, 0], Tb[:, 1], Tb[:, 2]).reshape(3, n).any(axis=0)
    lb2 = np.concatenate([B[:, 0], B[:, 1], B[:, 2]], axis=0)
    la2 = np.concatenate([B[:, 1], B[:, 2], B[:, 0]], axis=0)
    Ta = np.repeat(A, 3, axis=0)
    h2 = _seg_tri_norm(lb2, la2, Ta[:, 0], Ta[:, 1], Ta[:, 2]).reshape(3, n).any(axis=0)
    return h1 | h2


def _proj2d(P, axis):
    if axis == 0:
        return P[:, 1], P[:, 2]
    if axis == 1:
        return P[:, 0], P[:, 2]
    return P[:, 0], P[:, 1]


def _orient2d(ax, ay, bx, by, cx, cy):
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _coplanar_overlap(A, B, axis):
    """2D overlap test for coplanar pairs. Returns (overlap, touch)."""
    x0, y0 = _proj2d(A[:, 0], axis)
    x1, y1 = _proj2d(A[:, 1], axis)
    x2, y2 = _proj2d(A[:, 2], axis)
    u0, v0 = _proj2d(B[:, 0], axis)
    u1, v1 = _proj2d(B[:, 1], axis)
    u2, v2 = _proj2d(B[:, 2], axis)
    n = x0.shape[0]
    # scale for normalising orientation tests
    sc = np.maximum.reduce([
        np.abs(x1 - x0), np.abs(x2 - x0), np.abs(y1 - y0), np.abs(y2 - y0),
        np.abs(u1 - u0), np.abs(u2 - u0), np.abs(v1 - v0), np.abs(v2 - v0),
    ])
    sc = np.where(sc > 0, sc, 1.0)
    tol = E["eps_2d"] * sc * sc

    def on_seg(px, py, ax, ay, bx, by):
        inx = (px >= np.minimum(ax, bx) - np.sqrt(tol)) & (px <= np.maximum(ax, bx) + np.sqrt(tol))
        iny = (py >= np.minimum(ay, by) - np.sqrt(tol)) & (py <= np.maximum(ay, by) + np.sqrt(tol))
        return inx & iny

    def seg_seg(p, q, r, s):
        # p,q,r,s are (x,y) pairs; returns (cross, touch)
        d1 = _orient2d(r[0], r[1], s[0], s[1], p[0], p[1])
        d2 = _orient2d(r[0], r[1], s[0], s[1], q[0], q[1])
        d3 = _orient2d(p[0], p[1], q[0], q[1], r[0], r[1])
        d4 = _orient2d(p[0], p[1], q[0], q[1], s[0], s[1])
        # strict crossing (opposite signs on both) -> definite overlap
        cross = (((d1 > tol) & (d2 < -tol)) | ((d1 < -tol) & (d2 > tol))) & \
                (((d3 > tol) & (d4 < -tol)) | ((d3 < -tol) & (d4 > tol)))
        # degenerate/collinear contact, only when the point really lies on the other segment
        touch = ((np.abs(d1) <= tol) & on_seg(p[0], p[1], r[0], r[1], s[0], s[1])) | \
                ((np.abs(d2) <= tol) & on_seg(q[0], q[1], r[0], r[1], s[0], s[1])) | \
                ((np.abs(d3) <= tol) & on_seg(r[0], r[1], p[0], p[1], q[0], q[1])) | \
                ((np.abs(d4) <= tol) & on_seg(s[0], s[1], p[0], p[1], q[0], q[1]))
        return cross, touch

    any_cross = np.zeros(n, dtype=bool)
    any_touch = np.zeros(n, dtype=bool)
    A2 = [(x0, y0), (x1, y1), (x2, y2)]
    B2 = [(u0, v0), (u1, v1), (u2, v2)]
    for i in range(3):
        for j in range(3):
            c, t = seg_seg(A2[i], A2[(i + 1) % 3], B2[j], B2[(j + 1) % 3])
            any_cross |= c
            any_touch |= t
    # containment: all vertices of one triangle strictly inside the other
    def inside(px, py, a, b, c):
        d1 = _orient2d(a[0], a[1], b[0], b[1], px, py)
        d2 = _orient2d(b[0], b[1], c[0], c[1], px, py)
        d3 = _orient2d(c[0], c[1], a[0], a[1], px, py)
        return (((d1 > tol) & (d2 > tol) & (d3 > tol)) |
                ((d1 < -tol) & (d2 < -tol) & (d3 < -tol)))
    AinB = np.zeros(n, dtype=bool)
    BinA = np.zeros(n, dtype=bool)
    for k in range(3):
        AinB |= inside(A2[k][0], A2[k][1], B2[0], B2[1], B2[2])
        BinA |= inside(B2[k][0], B2[k][1], A2[0], A2[1], A2[2])
    overlap = any_cross | AinB | BinA
    return overlap, (~overlap) & any_touch


def classify(A, B):
    """A,B: (N,3,3). Returns array of kinds: 0 none, 1 transverse, 2 coplanar_overlap,
    3 coplanar_touch."""
    n = A.shape[0]
    if n == 0:
        return np.zeros(0, dtype=np.int8)
    nA = np.cross(A[:, 1] - A[:, 0], A[:, 2] - A[:, 0])
    nB = np.cross(B[:, 1] - B[:, 0], B[:, 2] - B[:, 0])
    lA = np.linalg.norm(nA, axis=1)
    lB = np.linalg.norm(nB, axis=1)
    lA = np.where(lA > 0, lA, 1.0)
    lB = np.where(lB > 0, lB, 1.0)
    cr = np.cross(nA, nB)
    sin_ang = np.linalg.norm(cr, axis=1) / (lA * lB)
    sep = np.abs(np.einsum('ij,ij->i', nA, B[:, 0] - A[:, 0])) / lA
    coplanar = (sin_ang <= E["eps_cop_sin"]) & (sep <= E["eps_cop_sep_m"])

    kind = np.zeros(n, dtype=np.int8)
    idx_cop = np.nonzero(coplanar)[0]
    idx_non = np.nonzero(~coplanar)[0]

    if idx_non.size:
        hit = _face_vs_face_transverse(A[idx_non], B[idx_non])
        kind[idx_non[hit]] = 1
    if idx_cop.size:
        # dominant axis of the shared normal -> drop it for the 2D projection
        nn = nA[idx_cop]
        axis = np.argmax(np.abs(nn), axis=1)  # 0,1,2 -> drop x,y,z
        for ax in (0, 1, 2):
            sel = idx_cop[axis == ax]
            if sel.size == 0:
                continue
            ov, tc = _coplanar_overlap(A[sel], B[sel], ax)
            kind[sel[ov]] = 2
            kind[sel[tc]] = 3
    return kind


# ---------------------------- self test ----------------------------
def _self_test():
    def T(*pts):
        return np.array([list(p) for p in pts], dtype=np.float64)

    cases = []
    # 1 transverse crossing (blade through ground)
    cases.append(("transverse", T([0, 0, 0], [1, 0, 0], [0, 1, 0]),
                  T([.5, .5, -.5], [.5, .5, .5], [1.5, .2, 0]), 1))
    # 2 coplanar overlap
    cases.append(("coplanar_overlap", T([0, 0, 0], [1, 0, 0], [0, 1, 0]),
                  T([.2, .2, 0], [.8, .2, 0], [.2, .8, 0]), 2))
    # 3 coplanar disjoint
    cases.append(("coplanar_disjoint", T([0, 0, 0], [1, 0, 0], [0, 1, 0]),
                  T([5, 0, 0], [6, 0, 0], [5, 1, 0]), 0))
    # 4 far apart, different planes
    cases.append(("far", T([0, 0, 0], [1, 0, 0], [0, 1, 0]),
                  T([0, 0, 5], [1, 0, 5], [0, 1, 5]), 0))
    # 5 parallel planes, no crossing
    cases.append(("parallel", T([0, 0, 0], [1, 0, 0], [0, 1, 0]),
                  T([0, 0, .1], [1, 0, .1], [0, 1, .1]), 0))
    # 6 coplanar, sharing only a single point (touch)
    cases.append(("coplanar_point_touch", T([0, 0, 0], [1, 0, 0], [0, 1, 0]),
                  T([1, 0, 0], [2, 0, 0], [1.5, -0.5, 0]), 3))
    # 7 containment, coplanar one inside other
    cases.append(("coplanar_contain", T([0, 0, 0], [3, 0, 0], [0, 3, 0]),
                  T([.5, .5, 0], [1, .5, 0], [.5, 1, 0]), 2))
    # 8 transverse with tiny det (near-degenerate but real) -- thin sliver crossing
    cases.append(("transverse_tiny", T([0, 0, 0], [1e-3, 0, 0], [0, 1e-3, 0]),
                  T([5e-4, 5e-4, -1e-4], [5e-4, 5e-4, 1e-4], [1.5e-3, 2e-4, 0]), 1))
    ok = True
    for name, a, b, want in cases:
        A = a[None, :, :]; B = b[None, :, :]
        k = int(classify(A, B)[0])
        flag = "OK " if k == want else "FAIL"
        if k != want:
            ok = False
        print(f"  [{flag}] {name}: kind={k} want={want}")
    print("SELFTEST", "PASS" if ok else "FAIL")
    return ok


if __name__ == '__main__':
    _self_test()
