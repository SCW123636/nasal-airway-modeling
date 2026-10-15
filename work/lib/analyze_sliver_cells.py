"""Locate the cells `checkMesh` flags as under-determined and say what they are.

Why this exists
---------------
`checkMesh -allGeometry -allTopology` on `b15_patient_maxh1_repaired.msh` said

    Cell determinant (wellposedness) : minimum: 1.11163982652e-07 average: 0.193855652104
 ***Cells with small determinant (< 0.001) found, number of cells: 585
 ***Faces with small interpolation weight (< 0.05) found, number of faces: 114
    Failed 2 mesh checks.

Calling checkMesh again only re-reports the count.  The decision we actually
need to make is *where the slivers come from*, because the two candidate causes
have completely different fixes:

  * surface cause - Netgen's surface optimiser bends the cap rims (the same
    effect that produced the +11% outlet area deviation), giving thin cells on
    the inlet/outlet patches;
  * repair cause   - `repair_boundary_tetrahedra.py` splits every tet with two
    exterior faces into four by adding the centroid.  Splitting an already-flat
    tet that way produces four flatter ones, so the repair that removed the
    determinant-zero cells may itself have created near-degenerate ones.

So for each flagged cell this script reports

  * whether it is a *surface* cell (has an exterior face) or an interior one,
    and which patch that exterior face belongs to;
  * whether the repair created it (via `split_cell_indices` and the in-place
    4-for-1 emission order in repair_boundary_tetrahedra.py:86-93).

Discipline note
---------------
The locally recomputed `cellDeterminant` does NOT reproduce checkMesh's numbers
(min 7.4e-08 vs 1.11e-07, count 575 vs 585, set overlap 497/585), so it is
reported but never used as the gate - the authoritative list of flagged cells is
checkMesh's own cellSet file.  `--selftest` pins the metric against an analytic
answer (a regular tetrahedron must give 8/27) so the implementation is known
correct even while the *formula* remains unmatched; the open question is whether
OpenFOAM normalises differently or whether writePrecision truncation on the
written polyMesh is responsible.

Usage
-----
    analyze_sliver_cells.py repaired.msh --cell-set underdeterminedCells.set \\
        --repair-json repaired.repair.json [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

# Outward-oriented vertex triples for a tet whose signed volume is positive.
TET_FACES = ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3))

# checkMesh's own numbers for this mesh (foam_b15_maxh1/checkMesh.log).
KNOWN = {'min_determinant': 1.11163982652e-07, 'n_small': 585,
         'average_determinant': 0.193855652104, 'threshold': 0.001,
         'n_low_weight_faces': 114, 'n_nonortho_faces': 204}


# --------------------------------------------------------------------------- io

def read_msh(path: Path):
    """Parse a Gmsh 2.2 ascii file: (points, triangles(0-based), tags, tets(0-based))."""
    with path.open('r', encoding='ascii', errors='replace') as fh:
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
                tets.append((int(parts[-4]), int(parts[-3]),
                             int(parts[-2]), int(parts[-1])))
    return (points,
            np.asarray(tris, dtype=np.int64) - 1,
            np.asarray(tags, dtype=np.int64),
            np.asarray(tets, dtype=np.int64) - 1)


def _keys(faces: np.ndarray, n_nodes: int) -> np.ndarray:
    f = np.sort(faces, axis=1).astype(np.int64)
    k = n_nodes + 1
    return (f[:, 0] * k + f[:, 1]) * k + f[:, 2]


def exterior_faces(tets: np.ndarray, triangles: np.ndarray, tags: np.ndarray,
                   n_nodes: int):
    """Return (n_exterior_per_cell, exterior_tag_per_cell), tag 0 = none.

    A tet face appearing exactly once is exterior; its physical tag comes from
    the matching boundary triangle, which also validates that the surface and the
    volume agree about where the boundary is.

    `exterior_tag_per_cell` is only well defined for cells with exactly one
    exterior face (last-writer-wins otherwise), so the count is returned too and
    an ambiguous cell is reported rather than silently given a wrong tag.  The
    repair guarantees no cell has two exterior faces
    (`cells_with_multiple_boundary_faces_remaining: 0`), but the unrepaired mesh
    deliberately has 4444 of them, so this must not be an error.
    """
    all_faces = np.concatenate([tets[:, cols] for cols in TET_FACES], axis=0)
    # concatenate emits every tet's first face, then every tet's second face,
    # so each face block repeats the complete cell-id sequence.
    face_of_tet = np.tile(np.arange(len(tets)), len(TET_FACES))
    keys = _keys(all_faces, n_nodes)

    tri_keys = _keys(triangles, n_nodes)
    if len(np.unique(tri_keys)) != len(tri_keys):
        raise SystemExit('boundary triangles are not unique')

    _, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
    is_exterior = counts[inverse] == 1
    if int(is_exterior.sum()) != len(triangles):
        raise SystemExit(
            f'exterior face count {int(is_exterior.sum())} != boundary triangle '
            f'count {len(triangles)} - surface and volume disagree')

    n_ext = np.bincount(face_of_tet[is_exterior], minlength=len(tets))

    tag_of_key = dict(zip(tri_keys.tolist(), tags.tolist()))
    ext_tag = np.zeros(len(tets), dtype=np.int64)
    unknown = 0
    for face_key, tet_id in zip(keys[is_exterior].tolist(),
                                face_of_tet[is_exterior].tolist()):
        tag = tag_of_key.get(face_key)
        if tag is None:
            unknown += 1
            continue
        ext_tag[tet_id] = tag
    if unknown:
        raise SystemExit(f'{unknown} exterior faces had no matching triangle tag')
    if int(n_ext.max()) > 1:
        print(f'  note: {int((n_ext > 1).sum())} cell(s) have more than one '
              f'exterior face (max {int(n_ext.max())}); their tag is ambiguous '
              f'and only the count is used')
    return n_ext, ext_tag


def read_set(path: Path) -> np.ndarray:
    text = path.read_text()
    m = re.search(r'\n\s*(\d+)\s*\n\s*\((.*?)\)', text, re.S)
    if m is None:
        raise SystemExit(f'{path}: could not locate the index list')
    body = re.sub(r'//.*', '', m.group(2))
    return np.fromstring(body, sep=' ', dtype=np.int64)


# --------------------------------------------------- cellDeterminant + selftest

def cell_determinant(points: np.ndarray, tets: np.ndarray) -> np.ndarray:
    """OpenFOAM-style metric: mag(det(sum_i aHat_i (x) aHat_i)) / 8."""
    v = points[tets]
    signed = np.einsum('ij,ij->i',
                       np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]),
                       v[:, 3] - v[:, 0]) / 6.0
    area_vecs = np.empty((len(tets), 4, 3), dtype=np.float64)
    for k, (a, b, c) in enumerate(TET_FACES):
        area_vecs[:, k, :] = 0.5 * np.cross(v[:, b] - v[:, a], v[:, c] - v[:, a])
    area_vecs *= np.sign(signed)[:, None, None]

    avg = np.linalg.norm(area_vecs, axis=2).mean(axis=1)      # (N,)
    safe = np.where(avg > 0, avg, 1.0)[:, None, None]
    a_hat = area_vecs / safe
    a_hat[avg <= 0] = 0.0
    tens = np.einsum('nki,nkj->nij', a_hat, a_hat)
    return np.abs(np.linalg.det(tens)) / 8.0, signed


def selftest() -> bool:
    """Pin the metric implementation against an analytic answer.

    For a regular tetrahedron the four outward unit face normals are
    (+-1,+-1,+-1)/sqrt(3) with even sign product.  Their outer-product sum is
    (4/3) I, so the metric is (4/3)^3 / 8 = 8/27.
    """
    a = 1.0
    pts = np.array([[a, a, a], [a, -a, -a], [-a, a, -a], [-a, -a, a]], dtype=float)
    tets = np.array([[0, 1, 2, 3]], dtype=np.int64)
    det, _ = cell_determinant(pts, tets)
    expected = 8.0 / 27.0
    ok = abs(det[0] - expected) < 1e-12
    print(f'selftest regular tetrahedron: metric {det[0]:.15f} '
          f'expected {expected:.15f} -> {"PASS" if ok else "FAIL"}')
    # a sliver (third point collapsed onto the first edge) must give ~0
    pts2 = np.array([[0, 0, 0], [1, 0, 0], [0.5, 1e-9, 0], [0.5, 0, 1e-9]], dtype=float)
    det2, _ = cell_determinant(pts2, tets)
    sliver_ok = det2[0] < 1e-15
    print(f'selftest sliver: metric {det2[0]:.3e} -> '
          f'{"PASS" if sliver_ok else "FAIL"}')
    return bool(ok and sliver_ok)


# ------------------------------------------------------------------ repair map

def repair_origin(n_output: int, split_cell_indices, n_input: int) -> np.ndarray:
    """Map each output cell index to its input cell index (repair line 86-93)."""
    split_set = set(int(i) for i in split_cell_indices)
    origin = np.empty(n_output, dtype=np.int64)
    out = 0
    for i in range(n_input):
        span = 4 if i in split_set else 1
        if out + span > n_output:
            raise SystemExit('repair origin mapping overflowed the output cell list')
        origin[out:out + span] = i
        out += span
    if out != n_output:
        raise SystemExit(f'repair origin mapping produced {out} of {n_output} cells')
    return origin


# ------------------------------------------------------------------------ main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('msh')
    ap.add_argument('--cell-set', help='checkMesh cellSet (authoritative)')
    ap.add_argument('--repair-json', help='repair report giving split_cell_indices')
    ap.add_argument('--json', help='write a summary JSON here')
    args = ap.parse_args(argv)

    print('=== selftest ===')
    metric_selftest_ok = selftest()

    path = Path(args.msh)
    points, tris, tags, tets = read_msh(path)
    print(f'\nfile     : {path}')
    print(f'points   : {len(points)}')
    print(f'triangles: {len(tris)}')
    print(f'tets     : {len(tets)}')

    n_ext, ext_tag = exterior_faces(tets, tris, tags, len(points))
    has_ext = n_ext > 0
    print(f'cells with an exterior face: {int(has_ext.sum())}')

    det, signed = cell_determinant(points, tets)
    n_small = int((det < KNOWN['threshold']).sum())
    rel = abs(det.min() - KNOWN['min_determinant']) / KNOWN['min_determinant']
    metric_ok = rel <= 1e-6 and n_small == KNOWN['n_small']
    print(f'\n=== locally recomputed cellDeterminant ===')
    print(f'  min {det.min():.11e}  average {det.mean():.12f}')
    print(f'  cells < {KNOWN["threshold"]}: {n_small}')
    print(f'  checkMesh known answer   : min {KNOWN["min_determinant"]:.11e}  '
          f'count {KNOWN["n_small"]}  average {KNOWN["average_determinant"]:.12f}')
    print(f'  METRIC: {"reproduced" if (metric_ok and metric_selftest_ok) else "NOT REPRODUCED"} '
          f'- {"usable as a gate" if metric_ok else "must not be used as a gate"}')

    if not args.cell_set:
        print('\nno --cell-set given, stopping here (the authoritative list of '
              'flagged cells comes from checkMesh, not from our metric)')
        return 0

    flagged = read_set(Path(args.cell_set))
    print(f'\n=== checkMesh underdeterminedCells (authoritative) ===')
    print(f'  flagged cells: {len(flagged)}  (expected {KNOWN["n_small"]})')
    if len(flagged) != KNOWN['n_small']:
        print('  WARNING: count differs from the checkMesh log line')

    mine = np.flatnonzero(det < KNOWN['threshold'])
    a, b = set(flagged.tolist()), set(mine.tolist())
    print(f'  vs our metric: agree {len(a & b)}, only checkMesh {len(a - b)}, '
          f'only ours {len(b - a)}')

    # ---- what are they
    sub = flagged
    n_surface = int(has_ext[sub].sum())
    print(f'\n=== character of the flagged cells ===')
    print(f'  surface cells (>=1 exterior face): {n_surface}/{len(sub)} '
          f'({100.0 * n_surface / len(sub):.1f}%)')
    print(f'  interior cells                   : {len(sub) - n_surface}')
    tag_names = {1: 'nostril_L', 2: 'nostril_R', 3: 'nasopharynx_outlet',
                 4: 'wall'}
    print('  exterior face patch of the flagged surface cells:')
    for tag in sorted(set(ext_tag[sub][has_ext[sub]].tolist())):
        n = int((ext_tag[sub] == tag).sum())
        print(f'    tag {tag} {tag_names.get(tag, "?")}: {n}')

    if args.repair_json:
        rep = json.loads(Path(args.repair_json).read_text())
        origin = repair_origin(len(tets), rep['split_cell_indices'],
                               rep['input_cells'])
        split_inputs = np.array(sorted(set(int(x) for x in rep['split_cell_indices'])))
        created = np.isin(origin, split_inputs)
        print(f'\n=== origin of the flagged cells (from {Path(args.repair_json).name}) ===')
        print(f'  repair-created (inside a split block): {int(created[sub].sum())}')
        print(f'  originally present                   : '
              f'{int((~created[sub]).sum())}')
        print(f'  (repair split {rep["split_cells"]} input cells, '
              f'{rep["input_cells"]} -> {rep["output_cells"]} cells)')
        if created[sub].any():
            c = sub[created[sub]]
            print(f'  repair-created flagged cells are surface cells: '
                  f'{int(has_ext[c].sum())}/{len(c)}')

    # ---- geometry
    print('\n=== geometry of the flagged cells ===')
    v = points[tets[sub]]
    edges = np.stack([np.linalg.norm(v[:, i] - v[:, j], axis=1)
                      for i, j in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))],
                     axis=1)
    vol = np.abs(signed[sub])
    print(f'  volume   : min {vol.min():.6e}  median {np.median(vol):.6e}  '
          f'max {vol.max():.6e}')
    print(f'  min edge : min {edges.min(axis=1).min():.6e}  '
          f'median {np.median(edges.min(axis=1)):.6e}  '
          f'max {edges.min(axis=1).max():.6e}')
    values, counts = np.unique(n_ext[sub], return_counts=True)
    ext_counts = {int(k): int(n) for k, n in zip(values, counts)}
    print(f'  exterior faces per flagged cell: {ext_counts}')

    # ---- write summary
    if args.json:
        payload = {
            'msh': str(path),
            'points': int(len(points)), 'triangles': int(len(tris)),
            'tets': int(len(tets)),
            'cells_with_exterior_face': int(has_ext.sum()),
            'exterior_faces_total': int(n_ext.sum()),
            'max_exterior_faces_per_cell': int(n_ext.max()),
            'metric_selftest_ok': bool(metric_selftest_ok),
            'metric_min': float(det.min()),
            'metric_average': float(det.mean()),
            'metric_n_below_threshold': int(n_small),
            'metric_reproduces_checkmesh': bool(metric_ok),
            'metric_usable_as_gate': bool(metric_ok and metric_selftest_ok),
            'checkmesh_known': KNOWN,
            'flagged_count': int(len(flagged)),
            'flagged_agree_with_metric': int(len(a & b)),
            'flagged_only_checkmesh': int(len(a - b)),
            'flagged_only_metric': int(len(b - a)),
            'flagged_surface_cells': n_surface,
            'flagged_interior_cells': int(len(sub) - n_surface),
            'flagged_by_patch_tag': {str(int(t)): int((ext_tag[sub] == t).sum())
                                     for t in sorted(set(ext_tag[sub].tolist()))
                                     if t != 0},
            'flagged_volume_m3': {'min': float(vol.min()),
                                  'median': float(np.median(vol)),
                                  'max': float(vol.max())},
            'flagged_min_edge_m': {'min': float(edges.min(axis=1).min()),
                                   'median': float(np.median(edges.min(axis=1))),
                                   'max': float(edges.min(axis=1).max())},
        }
        if args.repair_json:
            payload['flagged_repair_created'] = int(created[sub].sum())
            payload['flagged_original'] = int((~created[sub]).sum())
        Path(args.json).write_text(json.dumps(payload, indent=2))
        print(f'\nwrote {args.json}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
