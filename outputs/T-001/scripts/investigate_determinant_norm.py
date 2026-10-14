"""Investigate why the locally-recomputed cellDeterminant does not reproduce
checkMesh, and test the hypothesis that OpenFOAM normalises the face-area
vectors by the MAXIMUM face area of the cell (not the mean).

OpenFOAM (src/meshTools/meshCheck/meshCheck.C, meshChecks::cellDeterminant):

    const scalarField magSf(mag(fAreas[cFaces]));
    const scalar maxMagSf = max(magSf);          // <-- MAX, per cell
    tensor sumSST = Zero;
    forAll(cFaces, i)
    {
        vector aHat = fAreas[cFaces[i]] / maxMagSf;
        sumSST += sqr(aHat);
    }
    scalar determinant = 0.125 * mag(det(sumSST));

The previous local script used mag.mean(axis=1) as the normaliser.  This script
computes both variants and reports which one reproduces the known checkMesh
answer (min = 1.11163982652e-07, count(<0.001) = 585) for the repaired mesh.

Usage:
    investigate_determinant_norm.py <repaired.msh> <unrepaired.msh>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

TET_FACES = ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3))

KNOWN = {'min_determinant': 1.11163982652e-07, 'n_small': 585, 'threshold': 0.001}


def read_msh(path: Path):
    with path.open('r', encoding='ascii', errors='replace') as fh:
        for line in fh:
            if line.strip() == '$Nodes':
                break
        n_nodes = int(fh.readline())
        points = np.empty((n_nodes, 3), dtype=np.float64)
        for i in range(n_nodes):
            parts = fh.readline().split()
            points[i] = (float(parts[1]), float(parts[2]), float(parts[3]))
        for line in fh:
            if line.strip() == '$Elements':
                break
        n_elems = int(fh.readline())
        tets = []
        for _ in range(n_elems):
            parts = fh.readline().split()
            if int(parts[1]) == 4:
                tets.append((int(parts[-4]), int(parts[-3]), int(parts[-2]), int(parts[-1])))
    return points, np.asarray(tets, dtype=np.int64) - 1


def cell_determinant(points, tets, norm):
    """norm: 'mean' or 'max'."""
    v = points[tets]
    signed = np.einsum('ij,ij->i',
                       np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]),
                       v[:, 3] - v[:, 0]) / 6.0
    area_vecs = np.empty((len(tets), 4, 3), dtype=np.float64)
    for k, (a, b, c) in enumerate(TET_FACES):
        area_vecs[:, k, :] = 0.5 * np.cross(v[:, b] - v[:, a], v[:, c] - v[:, a])
    area_vecs *= np.sign(signed)[:, None, None]
    mag = np.linalg.norm(area_vecs, axis=2)
    if norm == 'max':
        scl = np.max(mag, axis=1)
    else:
        scl = mag.mean(axis=1)
    safe = np.where(scl > 0, scl, 1.0)[:, None, None]
    a_hat = area_vecs / safe
    a_hat[scl <= 0] = 0.0
    tens = np.einsum('nki,nkj->nij', a_hat, a_hat)
    return np.abs(np.linalg.det(tens)) / 8.0


def report(name, det):
    n_small = int((det < KNOWN['threshold']).sum())
    rel = abs(det.min() - KNOWN['min_determinant']) / KNOWN['min_determinant']
    match_min = rel <= 1e-6
    match_cnt = n_small == KNOWN['n_small']
    print(f'  {name}:')
    print(f'    min determinant      : {det.min():.11e}')
    print(f'    count (<0.001)       : {n_small}')
    print(f'    min rel diff vs CM   : {rel:.3e}  -> {"MATCH" if match_min else "mismatch"}')
    print(f'    count match vs CM    : {"MATCH" if match_cnt else "mismatch"} (CM={KNOWN["n_small"]})')
    return match_min and match_cnt


def main():
    repaired = Path(sys.argv[1])
    unrepaired = Path(sys.argv[2])
    for label, path in (('REPAIRED', repaired), ('UNREPAIRED', unrepaired)):
        print(f'\n=== {label}: {path} ===')
        points, tets = read_msh(path)
        print(f'  tets: {len(tets)}')
        for norm in ('mean', 'max'):
            det = cell_determinant(points, tets, norm)
            report(f'{norm}-norm', det)
    print('\nDONE')


if __name__ == '__main__':
    main()
