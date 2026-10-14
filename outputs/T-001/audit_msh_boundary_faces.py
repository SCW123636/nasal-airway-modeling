"""Audit a Gmsh 2.2 .msh: is every boundary triangle actually a face of a tet?

This exists because `gmshToFoam` reported

    Found 112818 undefined faces in mesh; adding to default patch defaultFaces

on `b15_patient_maxh1_repaired.msh`, while it handled the round-tube control
mesh fine.  The count 112818 equals the total number of boundary triangles, so
either

  (a) the triangles do not coincide with any tet face (a numbering/geometry
      bug on our side - repair, or the .msh writer), or
  (b) they do coincide and the converter is failing to associate them.

Reasoning about it from memory was not good enough - this script answers the
question on the actual artifact.  It rebuilds the same face bookkeeping that
`polyMeshFromShapeMesh` does:

  * every tet contributes its 4 faces to a multiset;
  * a face appearing exactly once is a true boundary face;
  * a triangle is only usable as a patch face if its key is present in that
    multiset.

Exit status is 0 when every triangle matches, 1 otherwise, so it can gate a
pipeline.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np


def read_elements(path: Path):
    """Return (triangles, tets) as 0-based int arrays, and the section header."""
    with path.open('r', encoding='ascii', errors='replace') as fh:
        for line in fh:
            if line.strip() == '$Elements':
                break
        else:
            raise SystemExit(f'{path}: no $Elements section found')
        n_elems = int(fh.readline())
        tris, tets = [], []
        tets_seen_after_tris = 0
        order_breaks = 0
        seen_tet = False
        for _ in range(n_elems):
            parts = fh.readline().split()
            if not parts:
                raise SystemExit(f'{path}: truncated $Elements section')
            etype = int(parts[1])
            if etype == 2:
                tris.append(parts[-3:])
                if seen_tet:
                    order_breaks += 1
            elif etype == 4:
                tets.append(parts[-4:])
                seen_tet = True
                tets_seen_after_tris += 1
            # other element types are irrelevant here
    return (np.asarray(tris, dtype=np.int64),
            np.asarray(tets, dtype=np.int64),
            {'n_elements_declared': n_elems,
             'triangles_before_any_tet_then_tet_appears': order_breaks,
             'n_tets_read': tets_seen_after_tris})


def face_keys(faces: np.ndarray, n_nodes: int) -> np.ndarray:
    """Encode sorted node triples as unique int64 keys."""
    f = np.sort(faces, axis=1).astype(np.int64)
    k = n_nodes + 1
    return (f[:, 0] * k + f[:, 1]) * k + f[:, 2]


TET_FACES = ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('msh')
    args = ap.parse_args(argv)

    path = Path(args.msh)
    tris1, tets1, meta = read_elements(path)
    if len(tris1) == 0 or len(tets1) == 0:
        raise SystemExit(f'{path}: expected both triangles and tets, got '
                         f'{len(tris1)} / {len(tets1)}')

    n_nodes = int(max(tris1.max(), tets1.max()))
    tris = tris1 - 1
    tets = tets1 - 1

    tet_faces = np.concatenate([tets[:, cols] for cols in TET_FACES], axis=0)
    tet_keys = face_keys(tet_faces, n_nodes)
    uniq, counts = np.unique(tet_keys, return_counts=True)
    boundary_keys = uniq[counts == 1]
    interior_keys = uniq[counts == 2]
    funny_keys = uniq[counts > 2]

    tri_keys = np.unique(face_keys(tris, n_nodes))

    matched = np.isin(tri_keys, uniq, assume_unique=True)
    # A triangle on an interior face would be a duplicate/explicit-face problem.
    on_interior = np.isin(tri_keys, interior_keys, assume_unique=True)

    missing_from_tris = np.setdiff1d(boundary_keys, tri_keys, assume_unique=True)
    extra_tris = np.setdiff1d(tri_keys, boundary_keys, assume_unique=True)

    print(f'file                    : {path}')
    print(f'declared elements       : {meta["n_elements_declared"]}')
    print(f'triangles (type 2)      : {len(tris)}')
    print(f'tets (type 4)           : {len(tets)}')
    print(f'  of which after a tet  : {meta["n_tets_read"]}')
    print(f'triangles seen after a tet already appeared: '
          f'{meta["triangles_before_any_tet_then_tet_appears"]}')
    print(f'highest node index      : {n_nodes}')
    print(f'--- tet face bookkeeping ---')
    print(f'unique tet faces        : {len(uniq)}')
    print(f'  appearing exactly once: {len(boundary_keys)}  <- true boundary faces')
    print(f'  appearing exactly twice: {len(interior_keys)}')
    print(f'  appearing >2 times    : {len(funny_keys)}')
    print(f'--- boundary triangles vs tet faces ---')
    print(f'unique triangle keys    : {len(tri_keys)}')
    print(f'triangles found in tet face list : {int(matched.sum())} '
          f'({100.0 * matched.mean():.2f}%)')
    print(f'triangles lying on an INTERIOR face : {int(on_interior.sum())}')
    print(f'boundary faces NOT covered by a triangle : {len(missing_from_tris)}')
    print(f'triangles not on the boundary (extra)    : {len(extra_tris)}')

    ok = bool(matched.all() and len(missing_from_tris) == 0)
    print()
    if ok:
        print('VERDICT: clean - every boundary triangle is a tet face and every '
              'boundary face has a triangle.  A converter failure on this file '
              'is NOT our geometry.')
    else:
        print('VERDICT: MISMATCH - the .msh itself is inconsistent; fix the '
              'writer/repair before blaming the converter.')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
