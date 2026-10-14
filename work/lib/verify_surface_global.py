# -*- coding: utf-8 -*-
"""
Global verification of a repaired surface: closed / manifold / min edge / min quality /
genuine self-intersections (strict tolerance, NON-ADJACENT face pairs only).

Design notes (why it is written this way):
  * Everything is vectorised and streaming: candidates are found, filtered and tested
    chunk by chunk; only the hit count is accumulated. Materialising all pairs on a
    ~220k-triangle airway needs tens of millions of pairs -> bad_alloc.
  * Search radius is per-triangle and derived from the real bounding-sphere radius
    r_i = max|vertex - centroid|. Two triangles can only intersect when
    |c_i - c_j| <= r_i + r_j, so the test stays COMPLETE while the candidate count
    drops hard versus a flat 2 mm radius.
  * Two radius passes keep completeness while avoiding a huge query radius:
      A: sources with r_i <= r_cap  -> query r_i + r_cap   (catches all pairs with both r <= r_cap)
      B: sources with r_i >  r_cap  -> query r_i + r_max   (catches every pair involving a big tri)
  * Adjacent pairs (sharing >= 1 vertex) are excluded: in a manifold mesh they touch
    legitimately and are not self-intersections.
Reuses the validated intersection kernel from decide_selfintersection_precision.py.
"""
import sys, json, argparse, math
import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, __file__.rsplit('\\', 1)[0])
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from decide_selfintersection_precision import (
    parse_stl, build_topology, seg_tri_vec
)


def mesh_metrics(verts, faces):
    """Vectorised per-face min edge / quality; returns global min, median, max edge."""
    p0 = verts[faces[:, 0]]
    p1 = verts[faces[:, 1]]
    p2 = verts[faces[:, 2]]
    l0 = np.linalg.norm(p1 - p0, axis=1)
    l1 = np.linalg.norm(p2 - p1, axis=1)
    l2 = np.linalg.norm(p0 - p2, axis=1)
    cross = np.cross(p1 - p0, p2 - p0)
    area = 0.5 * np.linalg.norm(cross, axis=1)
    denom = l0 * l0 + l1 * l1 + l2 * l2
    safe = np.where(denom > 0, denom, 1.0)
    qual = np.where(denom > 0, 4.0 * math.sqrt(3.0) * area / safe, 0.0)
    stack = np.concatenate([l0, l1, l2])
    return (float(np.min(np.minimum(np.minimum(l0, l1), l2))), float(np.min(qual)),
            float(np.median(stack)), float(np.max(stack)))


def edge_face_counts(faces):
    a = faces[:, 0]; b = faces[:, 1]; c = faces[:, 2]
    e1 = np.sort(np.stack([a, b], axis=1), axis=1)
    e2 = np.sort(np.stack([b, c], axis=1), axis=1)
    e3 = np.sort(np.stack([c, a], axis=1), axis=1)
    all_e = np.concatenate([e1, e2, e3], axis=0)
    _, cnt = np.unique(all_e, axis=0, return_counts=True)
    return {int(k): int((cnt == k).sum()) for k in np.unique(cnt)}


def _pairs_from_neighbours(src_ids, nb, cent, rad, faces, gi_min=None):
    """Vectorised: neighbour lists -> (src, dst) candidate pairs, filtered.

    Filters applied: dst > src (each pair once), bounding-sphere overlap,
    and non-adjacency (no shared vertex).
    """
    counts = np.fromiter((len(x) for x in nb), dtype=np.int64, count=len(nb))
    tot = int(counts.sum())
    if tot == 0:
        z = np.empty(0, dtype=np.int64)
        return z, z
    src = np.repeat(src_ids, counts)
    dst = np.concatenate([np.asarray(x, dtype=np.int64) for x in nb if len(x)])
    m = dst > src
    src, dst = src[m], dst[m]
    if src.size == 0:
        z = np.empty(0, dtype=np.int64)
        return z, z
    d = np.linalg.norm(cent[dst] - cent[src], axis=1)
    m = d <= (rad[src] + rad[dst]) + 1e-12
    src, dst = src[m], dst[m]
    if src.size == 0:
        z = np.empty(0, dtype=np.int64)
        return z, z
    fs = faces[src]; fd = faces[dst]
    shared = ((fs[:, 0:1] == fd).any(axis=1) |
              (fs[:, 1:2] == fd).any(axis=1) |
              (fs[:, 2:3] == fd).any(axis=1))
    return src[~shared], dst[~shared]


def _narrow(src, dst, faces, verts, eps=None):
    """Exact triangle-triangle classification. Returns array of kinds (0..3).

    Uses tri_tri_exact.classify, which is dimensionless in its degeneracy test and
    handles the coplanar case explicitly. `eps` is kept only for signature
    compatibility and is not used.
    """
    if src.size == 0:
        return np.empty(0, dtype=np.int8)
    from tri_tri_exact import classify
    return classify(verts[faces[src]], verts[faces[dst]])


def stream_intersections(verts, faces, eps=1e-9, chunk=800, verbose=True):
    cent = verts[faces].mean(axis=1)
    rad = np.linalg.norm(verts[faces] - cent[:, None, :], axis=2).max(axis=1)
    rmax = float(rad.max())
    rcap = float(np.percentile(rad, 99.5))
    tree = cKDTree(cent)
    F = len(faces)
    total_hit = 0
    total_cand = 0
    samples = []
    kind_pairs = {1: [], 2: [], 3: []}
    kind_counts = {1: 0, 2: 0, 3: 0}
    passes = [
        ("A:bulk", np.nonzero(rad <= rcap)[0], rcap),
        ("B:big", np.nonzero(rad > rcap)[0], rmax),
    ]
    for tag, ids, r_other in passes:
        if ids.size == 0:
            continue
        if verbose:
            print(f"  [{tag}] {ids.size} source tris, r_other={r_other*1e3:.4f} mm", flush=True)
        for s in range(0, ids.size, chunk):
            part = ids[s:s + chunk]
            nb = tree.query_ball_point(cent[part], rad[part] + r_other)
            src, dst = _pairs_from_neighbours(part, nb, cent, rad, faces)
            total_cand += int(src.size)
            kind = _narrow(src, dst, faces, verts, eps)
            hit = kind > 0
            nh = int(hit.sum())
            if nh:
                total_hit += nh
                for kk in (1, 2, 3):
                    sel = kind == kk
                    kind_counts[kk] += int(sel.sum())
                    if sel.any() and len(kind_pairs[kk]) < 20:
                        for a, b in zip(src[sel][:20], dst[sel][:20]):
                            if len(kind_pairs[kk]) < 20:
                                kind_pairs[kk].append([int(a), int(b)])
                for a, b in zip(src[hit][:20], dst[hit][:20]):
                    if len(samples) < 20:
                        samples.append([int(a), int(b)])
            if verbose and (s // chunk) % 25 == 0:
                print(f"    ...{s + len(part)}/{ids.size}  cand={total_cand} hits={total_hit}", flush=True)
    return total_hit, samples, total_cand, float(rcap), rmax, kind_counts, kind_pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stl', required=True)
    ap.add_argument('--eps', type=float, default=1e-9)
    ap.add_argument('--chunk', type=int, default=800)
    ap.add_argument('--output', default=None)
    args = ap.parse_args()

    tris = parse_stl(args.stl)
    verts, faces = build_topology(tris)
    mn_e, mn_q, med_e, max_e = mesh_metrics(verts, faces)
    cnt = edge_face_counts(faces)
    print(f"[mesh] {len(faces)} tris, {len(verts)} verts")
    print(f"[topo] edges-per-face-counts={cnt}  (all 2 => closed & manifold)")
    print(f"[qual] min_edge={mn_e:.6e} m ({mn_e*1e3:.6f} mm)  min_quality={mn_q:.6e}")
    print(f"[qual] median_edge={med_e*1e3:.4f} mm  max_edge={max_e*1e3:.4f} mm")
    if med_e * 1e3 > 5.0 or max_e * 1e3 > 50.0:
        print(f"[ABORT] implausible scale (median {med_e*1e3:.2f} mm, max {max_e*1e3:.2f} mm)")
        sys.exit(3)
    n, samples, ncand, rcap, rmax, kinds, kind_pairs = stream_intersections(
        verts, faces, eps=args.eps, chunk=args.chunk)
    print(f"[broad] {ncand} non-adjacent candidate pairs examined "
          f"(rcap={rcap*1e3:.4f} mm, rmax={rmax*1e3:.4f} mm)")
    print(f"[exact] transverse        = {kinds.get(1, 0)}")
    print(f"[exact] coplanar_overlap  = {kinds.get(2, 0)}")
    print(f"[exact] coplanar_touch    = {kinds.get(3, 0)}")
    print(f"[exact] TOTAL intersecting pairs = {n}")
    if samples:
        print(f"[exact] sample pairs: {samples[:20]}")

    res = {
        "stl": args.stl, "triangles": int(len(faces)), "vertices": int(len(verts)),
        "edge_face_counts": {str(k): v for k, v in cnt.items()},
        "closed_manifold": all(k == 2 for k in cnt),
        "min_edge_m": mn_e, "min_edge_mm": mn_e * 1e3, "min_quality": mn_q,
        "median_edge_mm": med_e * 1e3, "max_edge_mm": max_e * 1e3,
        "non_adjacent_candidate_pairs": int(ncand),
        "radius_cap_mm": rcap * 1e3, "radius_max_mm": rmax * 1e3,
        "exact_transverse": int(kinds.get(1, 0)),
        "exact_coplanar_overlap": int(kinds.get(2, 0)),
        "exact_coplanar_touch": int(kinds.get(3, 0)),
        "exact_total_intersecting_pairs": int(n),
        "exact_hit_pairs_sample": samples[:20],
    }
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(res, f, indent=2)
    print(json.dumps(res, indent=2))


if __name__ == '__main__':
    main()
