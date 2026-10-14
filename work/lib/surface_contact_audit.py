# -*- coding: utf-8 -*-
"""
Robust contact audit for a closed triangle surface.

Why this exists
---------------
The Moller-Trumbore based classifier (tri_tri_exact.classify) turned out to be
numerically unstable on this data: for grazing pairs the barycentric coordinate
u lands at ~1.1, i.e. right on the [0,1] boundary, and numpy's einsum summation
order changes with array length, so the SAME pair is a "hit" in one batch size
and a "miss" in another (measured: 39 hits all-at-once vs 1176 chunked, 1165
pairwise disagreements on p2_source). A measurement instrument that disagrees
with itself cannot be used to certify anything.

So this auditor only uses quantities that are numerically STABLE:
  * signed distance of a vertex to the other triangle's plane
        d = n . (P - Q0) / |n|
    (a single dot product, no cancellation of comparable magnitudes)
  * perpendicular triangle-triangle separation

Classification of a non-adjacent candidate pair:
    transverse   : the two triangles straddle each other's planes
                   (necessary AND sufficient for a real crossing, up to the
                   2D overlap which is implied for near-planar pairs)
    coplanar     : every vertex of both triangles lies within tol of the other's plane
    grazing      : neither, but the two triangles come within tol_g of each other
                   (surface nearly touches itself -- the meshing hazard)
    none         : everything else

Grazing contacts are reported separately because they are exactly what
OpenFOAM's tolerance-based surfaceCheck counts as "self-intersection" while not
being an actual crossing.
"""
import sys, json, argparse
import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, __file__.rsplit('\\', 1)[0])
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from decide_selfintersection_precision import parse_stl, build_topology
from verify_surface_global import _pairs_from_neighbours, mesh_metrics, edge_face_counts

# tolerances, in metres
TOL_PLANE = 1e-7     # "on the plane" band; float32 noise at |coord|~0.6 m is ~6e-8 m
TOL_GRAZE = 1e-6     # near-contact band (1 micron)


def tri_separation(A, B):
    """Perpendicular distances of each triangle's vertices to the other's plane."""
    nA = np.cross(A[:, 1] - A[:, 0], A[:, 2] - A[:, 0])
    nB = np.cross(B[:, 1] - B[:, 0], B[:, 2] - B[:, 0])
    lA = np.linalg.norm(nA, axis=1); lB = np.linalg.norm(nB, axis=1)
    lA = np.where(lA > 0, lA, 1.0); lB = np.where(lB > 0, lB, 1.0)
    # A's vertices w.r.t. B's plane; B's vertices w.r.t. A's plane
    dA = np.einsum('ij,ijk->ik', nB, A - B[:, 0][:, None, :]) / lB[:, None]
    dB = np.einsum('ij,ijk->ik', nA, B - A[:, 0][:, None, :]) / lA[:, None]
    return dA, dB


def min_vertex_gap(A, B):
    """Minimum vertex-to-vertex distance between the two triangles (N,)."""
    diff = A[:, :, None, :] - B[:, None, :, :]      # (N,3,3,3)
    return np.linalg.norm(diff, axis=3).min(axis=(1, 2))


def audit(verts, faces, chunk=800, verbose=True):
    cent = verts[faces].mean(axis=1)
    rad = np.linalg.norm(verts[faces] - cent[:, None, :], axis=2).max(axis=1)
    rmax = float(rad.max()); rcap = float(np.percentile(rad, 99.5))
    tree = cKDTree(cent)
    all_ids = np.arange(len(faces))
    counts = {"transverse": 0, "coplanar": 0, "grazing": 0, "none": 0}
    samples = {"transverse": [], "coplanar": [], "grazing": []}
    n_cand = 0
    for tag, ids, r_other in [("A", all_ids[rad <= rcap], rcap),
                              ("B", all_ids[rad > rcap], rmax)]:
        if ids.size == 0:
            continue
        for s in range(0, ids.size, chunk):
            part = ids[s:s + chunk]
            nb = tree.query_ball_point(cent[part], rad[part] + r_other)
            src, dst = _pairs_from_neighbours(part, nb, cent, rad, faces)
            if src.size == 0:
                continue
            n_cand += int(src.size)
            A = verts[faces[src]]; B = verts[faces[dst]]
            dA, dB = tri_separation(A, B)
            straddle_A = (dA > TOL_PLANE).any(axis=1) & (dA < -TOL_PLANE).any(axis=1)
            straddle_B = (dB > TOL_PLANE).any(axis=1) & (dB < -TOL_PLANE).any(axis=1)
            trans = straddle_A & straddle_B
            cop = (np.abs(dA) <= TOL_PLANE).all(axis=1) & (np.abs(dB) <= TOL_PLANE).all(axis=1)
            gap = min_vertex_gap(A, B)
            graz = (~trans) & (~cop) & (gap <= TOL_GRAZE)
            for key, mask in (("transverse", trans), ("coplanar", cop), ("grazing", graz)):
                n = int(mask.sum())
                counts[key] += n
                if n and len(samples[key]) < 20:
                    for a, b in zip(src[mask][:20], dst[mask][:20]):
                        if len(samples[key]) < 20:
                            samples[key].append([int(a), int(b)])
            counts["none"] += int((~trans & ~cop & ~graz).sum())
            if verbose and (s // chunk) % 50 == 0:
                print(f"  ...{s + len(part)}/{ids.size} cand={n_cand} "
                      f"trans={counts['transverse']} cop={counts['coplanar']} "
                      f"graz={counts['grazing']}", flush=True)
    return counts, samples, n_cand


def main():
    global TOL_PLANE, TOL_GRAZE
    ap = argparse.ArgumentParser()
    ap.add_argument('--stl', required=True)
    ap.add_argument('--output', default=None)
    ap.add_argument('--tol-plane', type=float, default=TOL_PLANE)
    ap.add_argument('--tol-graze', type=float, default=TOL_GRAZE)
    args = ap.parse_args()
    TOL_PLANE = args.tol_plane; TOL_GRAZE = args.tol_graze

    tris = parse_stl(args.stl)
    verts, faces = build_topology(tris)
    mn_e, mn_q, med_e, max_e = mesh_metrics(verts, faces)
    cnt = edge_face_counts(faces)
    print(f"[mesh] {len(faces)} tris, {len(verts)} verts")
    print(f"[topo] edges-per-face-counts={cnt}")
    print(f"[qual] min_edge={mn_e*1e3:.6f} mm  min_quality={mn_q:.6e}  "
          f"median_edge={med_e*1e3:.4f} mm  max_edge={max_e*1e3:.4f} mm")
    counts, samples, n_cand = audit(verts, faces)
    print(f"[cand ] {n_cand} non-adjacent candidate pairs")
    print(f"[TRANSVERSE] real crossings            = {counts['transverse']}")
    print(f"[COPLANAR  ] coplanar pairs            = {counts['coplanar']}")
    print(f"[GRAZING   ] near-contact (<{TOL_GRAZE*1e6:.0f} um)      = {counts['grazing']}")
    print(f"[none      ] clean                     = {counts['none']}")
    for k in ("transverse", "coplanar", "grazing"):
        if samples[k]:
            print(f"  sample {k}: {samples[k][:8]}")
    res = {
        "stl": args.stl, "triangles": int(len(faces)), "vertices": int(len(verts)),
        "edge_face_counts": {str(k): v for k, v in cnt.items()},
        "closed_manifold": all(k == 2 for k in cnt),
        "min_edge_mm": mn_e * 1e3, "min_quality": mn_q,
        "median_edge_mm": med_e * 1e3, "max_edge_mm": max_e * 1e3,
        "candidate_pairs": int(n_cand),
        "tol_plane_m": TOL_PLANE, "tol_graze_m": TOL_GRAZE,
        "counts": counts, "samples": samples,
    }
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(res, f, indent=2)


if __name__ == '__main__':
    main()
