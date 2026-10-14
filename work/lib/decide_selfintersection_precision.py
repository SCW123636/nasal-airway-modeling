# -*- coding: utf-8 -*-
"""
Decisive test for p2 / p3t1 self-intersection: real penetration vs float32 artifact.

OpenFOAM surfaceCheck v1912 stores STL vertices as float32 (STLpoint.H->floatVector,
STLAsciiParseI.H stores ASCII verts as float). A real anatomical self-fold is a geometric
feature present identically in float64 and float32 (above ~1e-6 mm). A float32
quantization artifact appears ONLY in the float32 representation.

Method:
  1. parse combined.stl (the exact file native checked)
  2. merge coincident vertices (float64) -> topology + adjacency (shared-vertex exclusion)
  3. broad-phase: cKDTree on centroids -> candidate face pairs within R
  4. narrow-phase: edge-triangle (Moller-Trumbore) intersection, excluding adjacency,
     vectorized over chunks
  5. evaluate the SAME face-pair list on float64 verts and float32-quantized verts
  6. verdict from the precision contrast

Decision:
  float64 ~ 0  AND  float32 >> 0  => native hits are float32 artifacts
  float64 >> 0                    => real penetration present (pairs reported)
"""
import sys, json, time, struct, argparse
import numpy as np
from scipy.spatial import cKDTree


def parse_stl(path):
    with open(path, 'rb') as f:
        f.read(80)
        nbin = struct.unpack('<I', f.read(4))[0]
        f.seek(0, 2)
        size = f.tell()
        if abs(size - (84 + 50 * nbin)) < 50:  # binary
            f.seek(84)
            data = f.read(50 * nbin)
            arr = np.frombuffer(data, dtype='<f4').reshape(nbin, 12)
            tris = np.empty((nbin, 3, 3), dtype=np.float64)
            tris[:, 0] = arr[:, 3:6]
            tris[:, 1] = arr[:, 6:9]
            tris[:, 2] = arr[:, 9:12]
            return tris
    # ASCII fallback
    verts = []
    with open(path, 'r', errors='ignore') as f:
        for line in f:
            ls = line.strip()
            if ls.startswith('vertex'):
                p = ls.split()
                verts.append((float(p[1]), float(p[2]), float(p[3])))
    return np.array(verts, dtype=np.float64).reshape(-1, 3, 3)


def build_topology(tris):
    flat = tris.reshape(-1, 3)
    key = np.round(flat / 1e-9).astype(np.int64)
    uniq_keys, first_idx = np.unique(key, axis=0, return_index=True)
    order = np.argsort(first_idx)
    uniq_keys = uniq_keys[order]
    uniq = flat[first_idx][order]
    lut = {tuple(uniq_keys[k]): k for k in range(len(uniq_keys))}
    faces = np.array([[lut[tuple(key[tris.shape[0]*0 + t*3 + 0])],  # placeholder, rebuild below
                      ]], dtype=np.int64) if False else None
    # rebuild faces from triangle->unique mapping
    tri2uniq = np.array([lut[tuple(key[k])] for k in range(flat.shape[0])], dtype=np.int64)
    faces = tri2uniq.reshape(-1, 3)
    return uniq, faces


def broad_phase(faces, verts, R):
    v0 = verts[faces[:, 0]]; v1 = verts[faces[:, 1]]; v2 = verts[faces[:, 2]]
    cent = (v0 + v1 + v2) / 3.0
    tree = cKDTree(cent)
    nb = tree.query_ball_point(cent, R)
    pairs = set()
    for i, nbrs in enumerate(nb):
        for j in nbrs:
            if j > i:
                pairs.add((i, j))
    return np.array(sorted(pairs), dtype=np.int64).reshape(-1, 2)


def seg_tri_vec(A, B, P0, P1, P2, eps=1e-9):
    # vectorized segment(a,b) vs triangle(p0,p1,p2); all (M,3)
    e1 = P1 - P0
    e2 = P2 - P0
    d = B - A
    n = np.cross(e1, e2)
    det = -np.einsum('ij,ij->i', d, n)
    valid = np.abs(det) >= eps
    inv = np.where(valid, 1.0 / np.where(valid, det, 1.0), 0.0)
    ao = A - P0
    t = np.einsum('ij,ij->i', ao, n) * inv
    u = np.einsum('ij,ij->i', ao, np.cross(d, e2)) * inv
    v = np.einsum('ij,ij->i', ao, np.cross(e1, d)) * inv
    hit = valid & (t >= -eps) & (t <= 1.0 + eps) & (u >= -eps) & (v >= -eps) & ((u + v) <= 1.0 + eps)
    return hit


def narrow_phase(pairs, faces, verts, chunk=200000, collect_details=False):
    P = pairs.shape[0]
    i = pairs[:, 0]; j = pairs[:, 1]
    fvi = verts[faces[i]]   # (P,3,3)
    fvj = verts[faces[j]]   # (P,3,3)
    total = 0
    hit_pairs = []
    details = []
    for s in range(0, P, chunk):
        e = min(s + chunk, P)
        pi = i[s:e]; pj = j[s:e]
        ai = fvi[s:e]; aj = fvj[s:e]
        shared = np.any(ai[:, :, None, :] == aj[:, None, :, :], axis=(1, 2, 3))
        A1 = np.concatenate([ai[:, 0], ai[:, 1], ai[:, 2]], axis=0)
        B1 = np.concatenate([ai[:, 1], ai[:, 2], ai[:, 0]], axis=0)
        T1 = np.repeat(aj, 3, axis=0)
        h1 = seg_tri_vec(A1, B1, T1[:, 0], T1[:, 1], T1[:, 2]).reshape(-1, 3)
        A2 = np.concatenate([aj[:, 0], aj[:, 1], aj[:, 2]], axis=0)
        B2 = np.concatenate([aj[:, 1], aj[:, 2], aj[:, 0]], axis=0)
        T2 = np.repeat(ai, 3, axis=0)
        h2 = seg_tri_vec(A2, B2, T2[:, 0], T2[:, 1], T2[:, 2]).reshape(-1, 3)
        hit1 = h1.any(axis=1)
        hit2 = h2.any(axis=1)
        hit = (hit1 | hit2) & (~shared)
        total += int(hit.sum())
        if hit.any():
            idx = np.nonzero(hit)[0]
            for kk in idx:
                k = kk + s
                hit_pairs.append((int(pairs[k, 0]), int(pairs[k, 1])))
                if collect_details:
                    details.append(_describe_hit(pairs[k, 0], pairs[k, 1], faces, verts))
    return total, hit_pairs, details


def _describe_hit(fi, fj, faces, verts):
    # determine which edge of which face crosses the other; report geometry
    fa = verts[faces[fi]]; fb = verts[faces[fj]]
    rec = {"face_i": int(fi), "face_j": int(fj), "edges_i_vs_j": [], "edges_j_vs_i": []}
    for k in range(3):
        a = fa[k]; b = fa[(k + 1) % 3]
        rec["edges_i_vs_j"].append(_seg_tri_detail(a, b, fb))
    for k in range(3):
        a = fb[k]; b = fb[(k + 1) % 3]
        rec["edges_j_vs_i"].append(_seg_tri_detail(a, b, fa))
    return rec


def _seg_tri_detail(a, b, tri):
    p0, p1, p2 = tri[0], tri[1], tri[2]
    e1 = p1 - p0; e2 = p2 - p0; d = b - a
    n = np.cross(e1, e2); det = -np.dot(d, n)
    if abs(det) < 1e-15:
        return {"crosses": False, "coplanar": True}
    inv = 1.0 / det; ao = a - p0
    t = np.dot(ao, n) * inv
    u = np.dot(ao, np.cross(d, e2)) * inv
    v = np.dot(ao, np.cross(e1, d)) * inv
    crosses = (0 <= t <= 1) and (u >= 0) and (v >= 0) and (u + v <= 1)
    # signed distance of endpoints to face plane
    nn = n / (np.linalg.norm(n) + 1e-30)
    d_a = float(np.dot(a - p0, nn)); d_b = float(np.dot(b - p0, nn))
    return {"crosses": bool(crosses), "t": float(t), "u": float(u), "v": float(v),
            "endpoint_dist_m": [d_a, d_b], "edge_len_m": float(np.linalg.norm(d)),
            "bary_u": float(u), "bary_v": float(v)}


def self_test():
    t1 = np.array([[0,0,0],[1,0,0],[0,1,0]], float)
    t2 = np.array([[0,0,0.5],[1,0,0.5],[0.5,0.5,-0.5]], float)  # crosses t1
    uniq, faces = build_topology(np.stack([t1, t2]))
    pairs = broad_phase(faces, uniq, R=2.0)
    h, _ = narrow_phase(pairs, faces, uniq.astype(np.float64))
    assert h == 1, f"intersecting expected 1 got {h}"
    a1 = np.array([[0,0,0],[1,0,0],[0,1,0]], float)
    a2 = np.array([[0,0,0],[1,0,0],[0,-1,0]], float)
    u2, f2 = build_topology(np.stack([a1, a2]))
    p2 = broad_phase(f2, u2, R=2.0)
    h2, _ = narrow_phase(p2, f2, u2.astype(np.float64))
    assert h2 == 0, f"adjacent expected 0 got {h2}"
    # separated
    s1 = np.array([[0,0,0],[1,0,0],[0,1,0]], float)
    s2 = np.array([[0,0,5],[1,0,5],[0,1,5]], float)
    u3, f3 = build_topology(np.stack([s1, s2]))
    p3 = broad_phase(f3, u3, R=2.0)
    h3, _ = narrow_phase(p3, f3, u3.astype(np.float64))
    assert h3 == 0, f"separated expected 0 got {h3}"
    print("self-test PASS: intersecting=1, adjacent=0, separated=0")


def focus_pairs(faces, verts, candidate_idx, R, radius_tree):
    v0 = verts[faces[:, 0]]; v1 = verts[faces[:, 1]]; v2 = verts[faces[:, 2]]
    cent = (v0 + v1 + v2) / 3.0
    tree = cKDTree(cent)
    cand = np.array(sorted(set(int(x) for x in candidate_idx)), dtype=np.int64)
    nb = tree.query_ball_point(cent[cand], radius_tree)
    rows = []
    for k, c in enumerate(cand):
        arr = np.asarray(nb[k], dtype=np.int64)
        arr = arr[arr != c]
        if arr.size:
            rows.append(np.stack([np.full(arr.shape, c), arr], axis=1))
    if not rows:
        return np.empty((0, 2), dtype=np.int64)
    allp = np.concatenate(rows, axis=0)
    lo = np.minimum(allp[:, 0], allp[:, 1])
    hi = np.maximum(allp[:, 0], allp[:, 1])
    keys = lo.astype(np.int64) * (allp[:, 1].max() + 1) + hi.astype(np.int64)
    _, uniq_idx = np.unique(keys, return_index=True)
    pairs = np.stack([lo[uniq_idx], hi[uniq_idx]], axis=1)
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stl', default=None)
    ap.add_argument('--native-hits', type=int, default=None)
    ap.add_argument('--radius', type=float, default=3.0)
    ap.add_argument('--focus', default=None, help='provenance json with candidate triangles')
    ap.add_argument('--focus-radius', type=float, default=2.0)
    ap.add_argument('--output', default=None)
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()
    if args.selftest:
        self_test(); return

    t0 = time.time()
    tris = parse_stl(args.stl)
    ntri = tris.shape[0]
    uniq, faces = build_topology(tris)
    print(f"[load] {ntri} tris, {len(uniq)} uniq verts ({time.time()-t0:.1f}s)")

    if args.focus:
        prov = json.load(open(args.focus, 'r', encoding='utf-8'))
        cand_idx = [c['triangle'] for c in prov.get('candidates', [])]
        print(f"[focus] {len(cand_idx)} candidate triangles from provenance")
        rm = args.focus_radius * 0.001  # mm -> m (STL stored in meters)
        pairs = focus_pairs(faces, uniq, cand_idx, rm, rm)
        print(f"[broad] {len(pairs)} candidate pairs (focus R={args.focus_radius}mm)")
    else:
        t1 = time.time()
        pairs = broad_phase(faces, uniq, args.radius * 0.001)
        print(f"[broad] {len(pairs)} candidate pairs (R={args.radius}mm) ({time.time()-t1:.1f}s)")

    h64, hp64, d64 = narrow_phase(pairs, faces, uniq.astype(np.float64), collect_details=True)
    print(f"[float64] genuine intersections = {h64}")
    uniq32 = uniq.astype(np.float32).astype(np.float64)
    h32, hp32, d32 = narrow_phase(pairs, faces, uniq32)
    print(f"[float32] genuine intersections = {h32}")

    verdict = "inconclusive"
    if h64 <= max(2, 0.05 * args.native_hits) and h32 >= 0.3 * args.native_hits:
        verdict = "float32_artifact"
    elif h64 >= 0.3 * args.native_hits:
        verdict = "real_penetration"
    result = {
        "stl": args.stl, "triangles": int(ntri), "unique_vertices": int(len(uniq)),
        "broad_phase_pairs": int(len(pairs)), "radius_mm": args.focus_radius if args.focus else args.radius,
        "native_surfacecheck_hits": int(args.native_hits),
        "float64_genuine_intersections": int(h64),
        "float32_genuine_intersections": int(h32),
        "float64_hit_pairs_sample": hp64[:50],
        "float32_hit_pairs_sample": hp32[:50],
        "float64_hit_details": d64,
        "verdict": verdict,
    }
    print(json.dumps(result, indent=2))
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        print(f"[out] wrote {args.output}")


if __name__ == '__main__':
    main()
