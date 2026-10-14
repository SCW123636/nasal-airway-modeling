"""Reproduce OpenFOAM's `cellDeterminant` (wellposedness) for a tet mesh, then
locate the under-determined cells it flags.

Why this exists
---------------
`checkMesh -allGeometry -allTopology` on the repaired patient mesh reported

    Cell determinant (wellposedness) : minimum: 1.11163982652e-07 average: 0.193855652104
 ***Cells with small determinant (< 0.001) found, number of cells: 585

Calling checkMesh again to find out *where* those 585 cells are is slow, and it
only tells us the count.  Worse, the project has been bitten repeatedly by
criteria that produced well-formed output that did not match reality, so a
locally-computed criterion is only trustworthy if it is checked against a known
answer.  This script therefore does both jobs:

  1. recompute the metric and assert it reproduces checkMesh's numbers
     (min = 1.11163982652e-07, count(<0.001) = 585) - the known answer;
  2. report the geometry of the flagged cells so we can see whether the slivers
     sit at the cap rims (where the Netgen surface optimiser bends the inlet and
     outlet planes) or are scattered through the wall region.

The metric is OpenFOAM's, verified earlier in this project to be dimensionless:

    cellDeterminant = mag(det(sum_i  aHat_i (x) aHat_i)) / 8
    aHat_i = faceAreaVector_i / mean_j |faceAreaVector_j|

`sqr(vector)` in OpenFOAM is the outer product, so the sum is a 3x3 tensor whose
determinant vanishes when all face normals become coplanar - exactly the sliver
case.  For a tetrahedron the four faces are known, and outward orientation is
fixed by the sign of the signed volume.

Exit status is 0 when the reproduction matches the known answer, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

# TET_FACES gives outward-oriented vertex triples *provided* the signed volume
# det([v1-v0, v2-v0, v3-v0]) is positive; otherwise every normal flips.
TET_FACES = ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3))

# Known answer from `checkMesh -allGeometry -allTopology` on
# b15_patient_maxh1_repaired.msh (log: foam_b15_maxh1/checkMesh.log).
KNOWN = {'min_determinant': 1.11163982652e-07, 'n_small': 585,
         'threshold': 0.001, 'average_determinant': 0.193855652104}


def read_msh(path: Path):
    """Parse a Gmsh 2.2 ascii file -> (points (N,3) float64, triangles, tags, tets)."""
    with path.open('r', encoding='ascii', errors='replace') as fh:
        # ---- nodes
        for line in fh:
            if line.strip() == '$Nodes':
                break
        else:
            raise SystemExit(f'{path}: no $Nodes section')
        n_nodes = int(fh.readline())
        points = np.empty((n_nodes, 3), dtype=np.float64)
        for i in range(n_nodes):
            parts = fh.readline().split()
            points[i] = (float(parts[1]), float(parts[2]), float(parts[3]))

        # ---- elements
        for line in fh:
            if line.strip() == '$Elements':
                break
        else:
            raise SystemExit(f'{path}: no $Elements section')
        n_elems = int(fh.readline())
        tris, tags, tets = [], [], []
        for _ in range(n_elems):
            parts = fh.readline().split()
            etype = int(parts[1])
            if etype == 2:
                tris.append((int(parts[-3]), int(parts[-2]), int(parts[-1])))
                tags.append(int(parts[3]))
            elif etype == 4:
                tets.append((int(parts[-4]), int(parts[-3]), int(parts[-2]), int(parts[-1])))
    return (points,
            np.asarray(tris, dtype=np.int64) - 1,
            np.asarray(tags, dtype=np.int64),
            np.asarray(tets, dtype=np.int64) - 1)


def cell_determinant(points: np.ndarray, tets: np.ndarray):
    """Return (cellDeterminant, signed_volume) arrays, OpenFOAM's metric."""
    v = points[tets]                     # (N, 4, 3)
    signed = np.einsum('ij,ij->i',
                       np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]),
                       v[:, 3] - v[:, 0]) / 6.0
    if np.any(signed == 0.0):
        n = int((signed == 0.0).sum())
        print(f'  note: {n} degenerate tet(s) with zero signed volume')

    # outward face area vectors
    area_vecs = np.empty((len(tets), 4, 3), dtype=np.float64)
    for k, (a, b, c) in enumerate(TET_FACES):
        area_vecs[:, k, :] = 0.5 * np.cross(v[:, b] - v[:, a], v[:, c] - v[:, a])
    area_vecs *= np.sign(signed)[:, None, None]

    mag = np.linalg.norm(area_vecs, axis=2)              # (N, 4)
    avg = mag.mean(axis=1)                               # (N,)
    safe = np.where(avg > 0, avg, 1.0)[:, None, None]    # (N, 1, 1)
    a_hat = area_vecs / safe
    a_hat[avg <= 0] = 0.0

    tens = np.einsum('nki,nkj->nij', a_hat, a_hat)       # (N, 3, 3)
    return np.abs(np.linalg.det(tens)) / 8.0, signed


def set_indices(path: Path) -> np.ndarray:
    """Read the integer list out of an OpenFOAM set file."""
    text = path.read_text()
    m = re.search(r'\n\s*(\d+)\s*\n\s*\((.*?)\)', text, re.S)
    if m is None:
        raise SystemExit(f'{path}: could not locate the index list')
    body = re.sub(r'//.*', '', m.group(2))
    return np.fromstring(body, sep=' ', dtype=np.int64)


def patch_planes(points, tris, tags):
    """Newell best-fit point+normal per physical tag (skip high-tag wall: too curved)."""
    out = {}
    for tag in sorted(set(tags.tolist())):
        sel = tris[tags == tag]
        p = points[sel]                                  # (M, 3, 3)
        n = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
        norm = np.linalg.norm(n, axis=1, keepdims=True)
        good = norm[:, 0] > 0
        n, p = n[good], p[good]
        n = n / np.linalg.norm(n, axis=1, keepdims=True)
        centroid = p.reshape(-1, 3).mean(axis=0)
        n_mean = n.mean(axis=0)
        nn = np.linalg.norm(n_mean)
        if nn == 0:
            continue
        out[int(tag)] = {'point': centroid, 'normal': n_mean / nn,
                         'n_triangles': int(len(sel))}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('msh')
    ap.add_argument('--cell-set', default=None,
                    help='OpenFOAM cellSet file listing the flagged cells')
    ap.add_argument('--check', action='store_true',
                    help='assert the known checkMesh answer (min/count)')
    ap.add_argument('--json', default=None, help='write a summary JSON here')
    args = ap.parse_args(argv)

    global KNOWN
    path = Path(args.msh)
    points, tris, tags, tets = read_msh(path)
    print(f'file        : {path}')
    print(f'points      : {len(points)}')
    print(f'triangles   : {len(tris)}')
    print(f'tets        : {len(tets)}')

    det, signed = cell_determinant(points, tets)
    n_small = int((det < KNOWN['threshold']).sum())
    print(f'cellDeterminant: min {det.min():.11e}  average {det.mean():.12f}')
    print(f'cells with determinant < {KNOWN["threshold"]}: {n_small}')
    print(f'(checkMesh known answer: min {KNOWN["min_determinant"]:.11e}, '
          f'count {KNOWN["n_small"]})')

    ok = True
    rel = abs(det.min() - KNOWN['min_determinant']) / KNOWN['min_determinant']
    print(f'  min relative difference vs checkMesh: {rel:.3e}')
    if rel > 1e-6:
        ok = False
        print('  MISMATCH: our metric does not reproduce checkMesh - do not '
              'trust the locations below.')
    if n_small != KNOWN['n_small']:
        ok = False
        print(f'  MISMATCH: count {n_small} != {KNOWN["n_small"]}')

    flagged = np.flatnonzero(det < KNOWN['threshold'])
    if args.cell_set:
        from_set = set_indices(Path(args.cell_set))
        print(f'\ncellSet file lists {len(from_set)} cells')
        a, b = set(flagged.tolist()), set(from_set.tolist())
        print(f'  agree            : {len(a & b)}')
        print(f'  only in ours     : {len(a - b)}')
        print(f'  only in the set  : {len(b - a)}')
        if a != b:
            ok = False

    # ---- geometry of the flagged cells
    print('\n--- flagged cell geometry ---')
    v = points[tets[flagged]]
    vol = np.abs(signed[flagged])
    edges = np.concatenate([np.linalg.norm(v[:, i] - v[:, j], axis=1)[:, None]
                            for i, j in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))],
                           axis=1)
    centroids = v.mean(axis=1)
    print(f'volume    : min {vol.min():.6e}  median {np.median(vol):.6e}  max {vol.max():.6e}')
    print(f'min edge  : min {edges.min():.6e}  median {np.median(edges.min(axis=1)):.6e}')
    print(f'max edge  : median {np.median(edges.max(axis=1)):.6e}')
    all_edges = []
    vt = points[tets]
    for i, j in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)):
        all_edges.append(np.linalg.norm(vt[:, i] - vt[:, j], axis=1))
    all_edges = np.concatenate(all_edges)
    print(f'(whole mesh) min edge {all_edges.min():.6e}  median '
          f'{np.median(all_edges):.6e}  max {all_edges.max():.6e}')

    planes = patch_planes(points, tris, tags)
    print('\ndistance from flagged-cell centroid to each cap plane:')
    near = {}
    for tag, pl in planes.items():
        d = np.abs((centroids - pl['point']) @ pl['normal'])
        near[tag] = d
        print(f'  tag {tag}: min {d.min()*1e3:.4f} mm  median {np.median(d)*1e3:.4f} mm  '
              f'max {d.max()*1e3:.4f} mm   <0.5mm: {int((d < 5e-4).sum())}/{len(d)}')

    within = np.zeros(len(flagged), dtype=bool)
    for d in near.values():
        within |= d < 5e-4
    print(f'\nflagged cells within 0.5 mm of a cap plane: {int(within.sum())} '
          f'of {len(flagged)} ({100.0 * within.mean():.1f}%)')

    if args.json:
        payload = {
            'msh': str(path),
            'points': int(len(points)), 'triangles': int(len(tris)), 'tets': int(len(tets)),
            'determinant_min': float(det.min()), 'determinant_average': float(det.mean()),
            'n_small_lt_0001': n_small,
            'reproduces_checkmesh': bool(ok),
            'flagged_within_0p5mm_of_cap_plane': int(within.sum()),
            'flagged_total': int(len(flagged)),
            'plane_distances_mm': {str(k): {'min': float(v2.min() * 1e3),
                                           'median': float(np.median(v2) * 1e3),
                                           'max': float(v2.max() * 1e3)}
                                   for k, v2 in near.items()},
        }
        Path(args.json).write_text(json.dumps(payload, indent=2))
        print(f'\nwrote {args.json}')

    print()
    print('VERDICT: ' + ('metric reproduced - locations are trustworthy'
                         if ok else 'NOT reproduced - investigate before use'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
