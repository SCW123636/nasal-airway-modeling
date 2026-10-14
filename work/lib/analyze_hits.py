# -*- coding: utf-8 -*-
"""
Characterise the exact-intersection hits: are they a localised anatomical pinch or a
systemic artifact of the test?

Reports:
  * distinct triangles involved vs total triangles
  * histogram of centroid distance and |sin(dihedral)|
  * spatial clusters (connected components of the hit-triangle adjacency graph)
  * per-cluster bounding box, so the location can be checked against anatomy
"""
import sys, json, argparse
import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, __file__.rsplit('\\', 1)[0])
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from decide_selfintersection_precision import parse_stl, build_topology
from verify_surface_global import _pairs_from_neighbours, mesh_metrics
from tri_tri_exact import classify


def collect_hits(verts, faces, chunk=800, verbose=True):
    cent = verts[faces].mean(axis=1)
    rad = np.linalg.norm(verts[faces] - cent[:, None, :], axis=2).max(axis=1)
    rmax = float(rad.max()); rcap = float(np.percentile(rad, 99.5))
    tree = cKDTree(cent)
    ids_all = np.arange(len(faces))
    out_src, out_dst, out_kind = [], [], []
    for tag, ids, r_other in [("A", ids_all[rad <= rcap], rcap), ("B", ids_all[rad > rcap], rmax)]:
        if ids.size == 0:
            continue
        for s in range(0, ids.size, chunk):
            part = ids[s:s + chunk]
            nb = tree.query_ball_point(cent[part], rad[part] + r_other)
            src, dst = _pairs_from_neighbours(part, nb, cent, rad, faces)
            if src.size == 0:
                continue
            kind = classify(verts[faces[src]], verts[faces[dst]])
            m = kind > 0
            if m.any():
                out_src.append(src[m]); out_dst.append(dst[m]); out_kind.append(kind[m])
            if verbose and (s // chunk) % 25 == 0:
                print(f"  ...{s+len(part)}/{ids.size}", flush=True)
    if not out_src:
        return np.empty(0, np.int64), np.empty(0, np.int64), np.empty(0, np.int8)
    return (np.concatenate(out_src), np.concatenate(out_dst), np.concatenate(out_kind))


def clusters(tri_ids, faces, verts):
    """Connected components among hit triangles (share a vertex)."""
    hit = set(int(t) for t in tri_ids)
    parent = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for t in hit:
        parent[t] = t
    vmap = {}
    for t in hit:
        for v in faces[t]:
            v = int(v)
            if v in vmap:
                union(vmap[v], t)
            else:
                vmap[v] = t
    groups = {}
    for t in hit:
        groups.setdefault(find(t), []).append(t)
    out = []
    for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        v = sorted(v)
        pts = verts[faces[v]].reshape(-1, 3)
        bb_min = pts.min(axis=0) * 1e3
        bb_max = pts.max(axis=0) * 1e3
        out.append({"n_triangles": len(v), "bbox_min_mm": [float(x) for x in bb_min],
                    "bbox_max_mm": [float(x) for x in bb_max],
                    "extent_mm": [float(bb_max[i] - bb_min[i]) for i in range(3)],
                    "sample_tris": v[:10]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stl', required=True)
    ap.add_argument('--output', default=None)
    ap.add_argument('--top-clusters', type=int, default=12)
    args = ap.parse_args()

    tris = parse_stl(args.stl)
    verts, faces = build_topology(tris)
    mn_e, mn_q, med_e, max_e = mesh_metrics(verts, faces)
    print(f"[mesh] {len(faces)} tris  min_edge={mn_e*1e3:.4f} mm  min_q={mn_q:.4f}  "
          f"median_edge={med_e*1e3:.4f} mm")
    src, dst, kind = collect_hits(verts, faces)
    n = len(src)
    print(f"[hits] {n} intersecting pairs")
    if n == 0:
        return
    dist = np.linalg.norm(verts[faces[src]].mean(axis=1) - verts[faces[dst]].mean(axis=1), axis=1) * 1e3
    nA = np.cross(verts[faces[src][:, 1]] - verts[faces[src][:, 0]],
                  verts[faces[src][:, 2]] - verts[faces[src][:, 0]])
    nB = np.cross(verts[faces[dst][:, 1]] - verts[faces[dst][:, 0]],
                  verts[faces[dst][:, 2]] - verts[faces[dst][:, 0]])
    na = np.linalg.norm(nA, axis=1); nb = np.linalg.norm(nB, axis=1)
    sinang = np.linalg.norm(np.cross(nA, nB), axis=1) / np.where(na * nb > 0, na * nb, 1.0)
    tri_ids = np.unique(np.concatenate([src, dst]))
    print(f"[spread] distinct triangles involved: {len(tri_ids)} / {len(faces)} "
          f"({100.0*len(tri_ids)/len(faces):.2f}%)")
    print(f"[dist ] centroid distance mm: min={dist.min():.4f} med={np.median(dist):.4f} max={dist.max():.4f}")
    print(f"[angle] |sin dihedral|: min={sinang.min():.3e} med={np.median(sinang):.3e} max={sinang.max():.3e}")
    for q in (1, 5, 25, 50, 75, 95):
        print(f"        p{q:<2d} sin={np.percentile(sinang, q):.3e}  dist={np.percentile(dist, q):.4f} mm")
    cl = clusters(tri_ids, faces, verts)
    print(f"[clusters] {len(cl)} connected clusters of hit triangles")
    for c in cl[:args.top_clusters]:
        print(f"   n={c['n_triangles']:5d}  extent={c['extent_mm'][0]:7.2f} x "
              f"{c['extent_mm'][1]:7.2f} x {c['extent_mm'][2]:7.2f} mm  "
              f"bbox_min=({c['bbox_min_mm'][0]:.2f}, {c['bbox_min_mm'][1]:.2f}, {c['bbox_min_mm'][2]:.2f})")
    res = {
        "stl": args.stl, "triangles": int(len(faces)),
        "min_edge_mm": mn_e * 1e3, "min_quality": mn_q,
        "hit_pairs": int(n),
        "kinds": {str(k): int((kind == k).sum()) for k in (1, 2, 3)},
        "distinct_triangles_involved": int(len(tri_ids)),
        "pct_triangles_involved": float(100.0 * len(tri_ids) / len(faces)),
        "centroid_dist_mm": {"min": float(dist.min()), "median": float(np.median(dist)),
                             "max": float(dist.max())},
        "sin_dihedral": {"min": float(sinang.min()), "median": float(np.median(sinang)),
                         "max": float(sinang.max())},
        "n_clusters": len(cl),
        "top_clusters": cl[:args.top_clusters],
    }
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(res, f, indent=2)


if __name__ == '__main__':
    main()
