"""Convert a SlicerVMTK `CFD Mesh Generator` output (.vtu, mm) into an OpenFOAM
polyMesh case, then report the numbers the project gates on.

The .vtu holds:
  * tetrahedra  - the volume cells, CellEntityIds = 0
  * triangles   - the boundary faces, CellEntityIds = 1 (wall) / >1 (caps)

Faces are rebuilt from the tetrahedra (each tet contributes its 4 faces), so the
orientation of every face is taken from the cell that owns it - outward from the
owner - which is exactly OpenFOAM's convention.  Faces that coincide with a
boundary triangle become boundary faces and take that triangle's patch id.

    python vtu_to_openfoam.py <case.vtu> <out_case_dir> [--unit-scale 0.001] [--binary]

Units: the .vtu is in millimetres; OpenFOAM wants metres, hence unit-scale 1e-3.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import meshio
import numpy as np

# Local faces of a positively oriented VTK tetrahedron, outward-facing.
TET_FACES = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [0, 3, 2]], dtype=np.int64)


def foam_header(cls, obj, location="constant/polyMesh"):
    return (
        "/*--------------------------------*- C++ -*----------------------------------*\\\n"
        "| =========                 |                                                 |\n"
        "| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |\n"
        "|  \\\\    /   O peration     | Version:  v1912                                 |\n"
        "|   \\\\  /    A nd           | Website:  www.openfoam.com                      |\n"
        "|    \\\\/     M anipulation  |                                                 |\n"
        "\\*---------------------------------------------------------------------------*/\n"
        "FoamFile\n"
        "{\n"
        "    version     2.0;\n"
        "    format      ascii;\n"
        f"    class       {cls};\n"
        f"    location    \"{location}\";\n"
        f"    object      {obj};\n"
        "}\n"
        "// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //\n\n"
    )


def write_labels(path, obj, values, cls="labelList"):
    v = np.asarray(values, dtype=np.int64)
    out = [foam_header(cls, obj), f"{len(v)}\n(\n"]
    out.append("\n".join(str(int(x)) for x in v))
    out.append("\n)\n\n// ************************************************************************* //\n")
    Path(path).write_text("".join(out), encoding="ascii")


def write_faces(path, faces, cls="faceList"):
    out = [foam_header(cls, "faces"), f"{len(faces)}\n(\n"]
    for f in faces:
        out.append(f"{len(f)}({' '.join(str(int(x)) for x in f)})\n")
    out.append(")\n\n// ************************************************************************* //\n")
    Path(path).write_text("".join(out), encoding="ascii")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("vtu")
    ap.add_argument("outdir")
    ap.add_argument("--unit-scale", type=float, default=0.001, help="mm -> m")
    ap.add_argument("--patch-names", default="wall", help="comma list, id 1..N")
    ap.add_argument("--report", default=None)
    args = ap.parse_args(argv)

    vtu = Path(args.vtu)
    out = Path(args.outdir)
    poly = out / "constant" / "polyMesh"
    poly.mkdir(parents=True, exist_ok=True)

    m = meshio.read(vtu)
    ids = np.zeros(len(m.cells) and sum(len(cb.data) for cb in m.cells) or 0, dtype=np.int64)
    off = 0
    for i, cb in enumerate(m.cells):
        n = len(cb.data)
        for name, arr in m.cell_data.items():
            if name == "CellEntityIds":
                a = np.asarray(arr[i])
                ids[off:off + n] = a.reshape(n, -1)[:, 0]
        off += n

    def block(t):
        off = 0
        for i, cb in enumerate(m.cells):
            n = len(cb.data)
            if cb.type == t:
                return cb.data.astype(np.int64), ids[off:off + n]
            off += n
        return np.zeros((0, 0), np.int64), np.zeros(0, np.int64)

    T, Tids = block("tetra")
    B, Bids = block("triangle")
    report = {"vtu": str(vtu), "points": int(len(m.points)),
              "tets": int(len(T)), "boundary_triangles": int(len(B)),
              "unit_scale": args.unit_scale}

    P = m.points * args.unit_scale

    # orientation of the tetrahedra: flip any with non-positive volume
    v0, v1, v2, v3 = (P[T[:, i]] for i in range(4))
    vol6 = np.einsum("ij,ij->i", v1 - v0, np.cross(v2 - v0, v3 - v0))
    bad = vol6 <= 0
    report["tets_nonpositive_volume"] = int(bad.sum())
    if bad.any():
        T[bad] = T[bad][:, [0, 2, 1, 3]]
    tet_vol = np.abs(vol6) / 6.0
    report["mesh_volume_m3"] = float(tet_vol.sum())

    NP = len(P) + 1
    def key3(a):
        s = np.sort(a, axis=-1)
        return (s[..., 0] * NP + s[..., 1]) * NP + s[..., 2]

    tet_faces = T[:, TET_FACES]                      # (nT, 4, 3)
    nT = len(T)
    cells = np.repeat(np.arange(nT, dtype=np.int64), 4)
    fkeys = key3(tet_faces).reshape(-1)
    fverts = tet_faces.reshape(-1, 3)
    bkeys = key3(B)

    order = np.argsort(bkeys)
    bkeys_s = bkeys[order]
    mask = np.zeros(len(fkeys), dtype=bool)
    pos = np.searchsorted(bkeys_s, fkeys)
    pos_c = np.clip(pos, 0, max(len(bkeys_s) - 1, 0))
    if len(bkeys_s):
        mask = (pos < len(bkeys_s)) & (bkeys_s[pos_c] == fkeys)
    report["tet_faces_total"] = int(len(fkeys))
    report["tet_faces_on_boundary"] = int(mask.sum())
    report["boundary_triangles_unmatched"] = int(len(bkeys) - mask.sum())
    report["holes_expected"] = int(len(bkeys) - mask.sum())

    # boundary faces, oriented outward from their own tet
    bface_v = fverts[mask]
    bface_cell = cells[mask]
    bface_key = fkeys[mask]

    # internal faces: the rest, each appearing exactly twice
    ikeys = fkeys[~mask]
    iverts = fverts[~mask]
    icells = cells[~mask]
    so = np.argsort(ikeys, kind="stable")
    ikeys_s, iverts_s, icells_s = ikeys[so], iverts[so], icells[so]
    if len(ikeys_s) % 2:
        report["internal_face_parity_error"] = True
    a_i, b_i = iverts_s[0::2], iverts_s[1::2]
    ca, cb = icells_s[0::2], icells_s[1::2]
    report["internal_face_key_mismatch"] = int((ikeys_s[0::2] != ikeys_s[1::2]).sum())
    owner_i = np.minimum(ca, cb)
    neigh_i = np.maximum(ca, cb)
    face_i = np.where((ca <= cb)[:, None], a_i, b_i)

    # boundary patch ids -> patch index
    names = [s.strip() for s in args.patch_names.split(",")]
    bface_adj = bface_cell
    b_pid = Bids[np.searchsorted(bkeys_s, bface_key)]
    uniq = sorted(set(int(x) for x in np.unique(b_pid)))
    id2patch = {}
    nextp = 0
    for u in uniq:
        if u in (0,):
            continue
        id2patch[u] = nextp
        nextp += 1
    while len(names) < nextp:
        names.append("patch%d" % len(names))
    patch_of = np.array([id2patch.get(int(u), -1) for u in b_pid], dtype=np.int64)
    report["boundary_id_histogram"] = {str(k): int(v) for k, v in
                                       sorted(Counter(b_pid.tolist()).items())}
    report["patches"] = names[:nextp]

    # face order: all internal faces, then boundary faces grouped by patch
    n_int = len(face_i)
    write_labels(poly / "owner", "owner",
                 np.concatenate([owner_i, bface_adj]) if len(bface_adj) else owner_i)
    write_labels(poly / "neighbour", "neighbour", neigh_i)

    all_faces = [face_i]
    counts = []
    for p in range(nextp):
        sel = np.flatnonzero(patch_of == p)
        counts.append((names[p], len(sel), n_int + int(sel[0]) if len(sel) else n_int))
        all_faces.append(bface_v[sel])
    write_faces(poly / "faces", np.concatenate(all_faces))

    # points
    vout = [foam_header("vectorField", "points"), f"{len(P)}\n(\n"]
    vout.append("\n".join("(%.9g %.9g %.9g)" % tuple(row) for row in P))
    vout.append("\n)\n\n// ************************************************************************* //\n")
    (poly / "points").write_text("".join(vout), encoding="ascii")

    # boundary
    bout = [foam_header("polyBoundaryMesh", "boundary"),
            f"{nextp}\n(\n"]
    for name, nf, sf in counts:
        bout.append("    %s\n    {\n        type            wall;\n"
                    "        nFaces          %d;\n        startFace       %d;\n    }\n"
                    % (name, nf, sf))
    bout.append(")\n\n// ************************************************************************* //\n")
    (poly / "boundary").write_text("".join(bout), encoding="ascii")

    report["polyMesh"] = {"points": int(len(P)), "faces": int(len(face_i) + len(bface_v)),
                          "internal_faces": int(n_int),
                          "boundary_faces": int(len(bface_v)),
                          "cells": int(nT), "patches": counts}
    rep_path = Path(args.report) if args.report else out / "convert_report.json"
    rep_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "boundary_id_histogram"},
                     indent=2)[:4000])
    print("WROTE", rep_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
