"""T-011 A.1 - report OpenFOAM patch areas and total volume directly from an
ASCII polyMesh, so a snappyHexMesh result can be checked against the surface
areas the opening stage recorded (nostril_L 80.2554 / nostril_R 80.4579 /
oropharynx_truncation_outlet 225.9962 mm^2 for p0).

Why a parser instead of an OpenFOAM utility: this needs no field to exist, so it
can validate the mesh before any 0/ directory is written, and it doubles as the
"does the snappy mesh reproduce the surface areas" gate.

Usage: python3 foam_patch_areas.py [case_dir]
"""
import re
import sys
from pathlib import Path

import numpy as np

CASE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/home/lenovo2/t011_p0/snappy')
PM = CASE / 'constant' / 'polyMesh'


def strip_comments(txt):
    txt = re.sub(r'/\*.*?\*/', '', txt, flags=re.S)
    return re.sub(r'//[^\n]*', '', txt)


def read_points(path):
    txt = strip_comments(path.read_text(errors='ignore'))
    vals = re.findall(r'\(([^()]*)\)', txt)
    pts = [tuple(float(x) for x in v.split()) for v in vals if len(v.split()) == 3]
    return np.asarray(pts, dtype=float)


def read_faces(path):
    txt = strip_comments(path.read_text(errors='ignore'))
    # drop the FoamFile header first: its "version 2.0" would otherwise be
    # tokenised as the face count (2) and a stray index.
    txt = re.sub(r'FoamFile\s*\{[^{}]*\}', '', txt, flags=re.S)
    toks = re.findall(r'\d+|\(|\)', txt)
    i = 0
    nf = int(toks[i]); i += 1
    if toks[i] == '(':
        i += 1
    faces = []
    for _ in range(nf):
        n = int(toks[i]); i += 1
        if toks[i] == '(':
            i += 1
            idx = [int(toks[i + k]) for k in range(n)]
            i += n
            if toks[i] == ')':
                i += 1
        else:
            idx = [int(toks[i + k]) for k in range(n)]
            i += n
        faces.append(idx)
    return faces


def read_boundary(path):
    txt = strip_comments(path.read_text(errors='ignore'))
    out = []
    for m in re.finditer(r'(\w+)\s*\{([^{}]*)\}', txt, flags=re.S):
        name, body = m.group(1), m.group(2)
        nf = re.search(r'nFaces\s+(\d+)', body)
        sf = re.search(r'startFace\s+(\d+)', body)
        ty = re.search(r'type\s+(\w+)', body)
        if nf and sf:
            out.append((name, ty.group(1) if ty else '?', int(sf.group(1)), int(nf.group(1))))
    return out


def poly_area(P, idx):
    if len(idx) < 3:
        return 0.0
    Q = P[idx]
    a = 0.0
    for k in range(1, len(idx) - 1):
        a += 0.5 * float(np.linalg.norm(np.cross(Q[k] - Q[0], Q[k + 1] - Q[0])))
    return a


def main():
    P = read_points(PM / 'points')
    faces = read_faces(PM / 'faces')
    patches = read_boundary(PM / 'boundary')
    print('case          : %s' % CASE)
    print('points / faces: %d / %d' % (len(P), len(faces)))
    print('patches       : %d' % len(patches))
    print()
    print('%-32s %8s %10s %14s' % ('patch', 'type', 'nFaces', 'area_mm2'))
    total = 0.0
    for name, ty, sf, nf in patches:
        a = sum(poly_area(P, faces[sf + k]) for k in range(nf))
        total += a
        print('%-32s %8s %10d %14.4f' % (name, ty, nf, a * 1e6))
    print('%-32s %8s %10s %14.4f' % ('ALL BOUNDARY', '', '', total * 1e6))

    # enclosed volume by the divergence theorem, computed about a reference
    # point INSIDE the bbox: the raw q0.(q1 x q2) form suffers catastrophic
    # cancellation here because the mesh sits ~0.6 m from the origin while the
    # domain is only ~0.08 m across.
    r = P.mean(axis=0)
    vol = 0.0
    for f in faces:
        Q = P[f] - r
        for k in range(1, len(f) - 1):
            vol += np.dot(Q[0], np.cross(Q[k], Q[k + 1])) / 6.0
    print()
    print('enclosed volume (divergence theorem): %.4f mm^3' % (abs(vol) * 1e9))


if __name__ == '__main__':
    main()
