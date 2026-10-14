"""Reconstruct OpenFOAM's cellDeterminant from the ACTUAL polyMesh that
checkMesh reads, to pin down why the msh-based local recompute did not match.

We test four combinations of the two conventions OpenFOAM could be using:
  * orientation: 'raw'   = face area vectors as stored (outward from owner; for a
                            neighbour cell one face is inward -> mixed)
                 'cons'  = flip every face so all four point outward from the cell
  * normalisation: 'mean' = divide aHat by mean face area of the cell
                  'max'  = divide aHat by max  face area of the cell

Known checkMesh answer (foam_repaired): min 1.11163982652e-07, count(<0.001)=585.

Usage: reconstruct_determinant_from_polymesh.py <polyMeshDir>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


def read_polymesh(d: Path):
    def read_field(name):
        txt = (d / name).read_text()
        # locate the integer count after the FoamFile header
        # format: FoamFile {...} <count> ( ... )
        # find first bare integer line then '('
        lines = txt.splitlines()
        # skip until we find a line that is just an integer
        i = 0
        while i < len(lines):
            s = lines[i].strip()
            if s.isdigit():
                n = int(s)
                # next non-empty should be '('
                j = i + 1
                while j < len(lines) and lines[j].strip() == '':
                    j += 1
                assert lines[j].strip() == '(', lines[j]
                body = []
                k = j + 1
                while k < len(lines) and lines[k].strip() != ')':
                    body.append(lines[k])
                    k += 1
                return n, body
            i += 1
        raise RuntimeError(f'{name}: could not parse')

    def clean(body):
        out = []
        for l in body:
            s = l.replace('(', ' ').replace(')', ' ').split()
            out.append(s)
        return out

    npts, pts_body = read_field('points')
    pts_c = clean(pts_body)
    points = np.array([[float(x) for x in l[:3]] for l in pts_c], dtype=np.float64)

    nfaces, faces_body = read_field('faces')
    faces_c = clean(faces_body)
    faces = [np.array([int(x) for x in l[1:]], dtype=np.int64) for l in faces_c]  # drop leading node count

    _, owner_body = read_field('owner')
    owner = np.array([int(x) for x in owner_body], dtype=np.int64)

    # neighbour file only exists for internal faces
    neigh = None
    if (d / 'neighbour').exists():
        _, nb = read_field('neighbour')
        neigh = np.array([int(x) for x in nb], dtype=np.int64)

    return points, faces, owner, neigh


def face_area_vec(points, nodes):
    # Newell-ish area vector via triangle fan from node 0
    p0 = points[nodes[0]]
    s = np.zeros(3)
    for a, b in zip(nodes[1:-1], nodes[2:]):
        s += np.cross(points[a] - p0, points[b] - p0)
    return 0.5 * s


def main():
    d = Path(sys.argv[1])
    points, faces, owner, neigh = read_polymesh(d)
    print(f'points={len(points)} faces={len(faces)} owner={len(owner)} neigh={None if neigh is None else len(neigh)}')

    maxc = int(owner.max())
    if neigh is not None:
        maxc = max(maxc, int(neigh.max()))
    n_cells = maxc + 1
    # cell -> list of face indices
    cell_faces = [[] for _ in range(n_cells)]
    for fi, c in enumerate(owner):
        cell_faces[c].append(fi)
    if neigh is not None:
        for fi, c in enumerate(neigh):
            cell_faces[c].append(fi)

    # precompute raw area vectors (outward from owner, as OpenFOAM stores)
    raw_sf = np.array([face_area_vec(points, f) for f in faces], dtype=np.float64)
    # fix orientation to point away from owner centroid (robustness)
    centroids_cells = np.zeros((n_cells, 3))
    counts = np.zeros(n_cells)
    for fi, c in enumerate(owner):
        centroids_cells[c] += points[faces[fi]].mean(axis=0)
        counts[c] += 1
    centroids_cells /= counts[:, None]
    for fi in range(len(faces)):
        c = owner[fi]
        # ensure raw_sf points away from owner centroid
        if np.dot(raw_sf[fi], points[faces[fi]].mean(axis=0) - centroids_cells[c]) < 0:
            raw_sf[fi] = -raw_sf[fi]

    KNOWN_MIN = 1.11163982652e-07
    KNOWN_N = 585
    THRESH = 0.001

    for orient in ('raw', 'cons'):
        for norm in ('mean', 'max'):
            dets = np.empty(n_cells)
            for ci in range(n_cells):
                fl = cell_faces[ci]
                sf = raw_sf[fl].copy()
                if orient == 'cons':
                    # flip faces that are inward to this cell
                    for idx, f in enumerate(fl):
                        if ci != owner[f]:
                            sf[idx] = -sf[idx]
                mag = np.linalg.norm(sf, axis=1)
                scl = mag.mean() if norm == 'mean' else mag.max()
                ahat = sf / scl if scl > 0 else sf * 0
                tens = np.einsum('ki,kj->ij', ahat, ahat)
                dets[ci] = np.abs(np.linalg.det(tens)) / 8.0
            n_small = int((dets < THRESH).sum())
            rel = abs(dets.min() - KNOWN_MIN) / KNOWN_MIN
            ok = (rel <= 1e-6) and (n_small == KNOWN_N)
            print(f'  orient={orient:4s} norm={norm:4s}: min={dets.min():.11e} '
                  f'count={n_small:6d} relmin={rel:.2e} -> {"MATCH" if ok else "mismatch"}')
    print('DONE')


if __name__ == '__main__':
    main()
