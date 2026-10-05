"""Split boundary tetrahedra while preserving all original faces and tags.

This is an experimental mesh preparation step, not a quality acceptance.
Every result still requires the unchanged OpenFOAM mesh and solver gates.
Requires meshio and numpy in the meshing environment.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import meshio
import numpy as np


FACE_VERTICES = ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))


def repair(source: Path, target: Path) -> dict:
    mesh = meshio.read(source)
    if set(mesh.cells_dict) != {"triangle", "tetra"}:
        raise ValueError("expected only boundary triangles and linear tetrahedra")
    points = np.asarray(mesh.points, dtype=float)
    triangles = mesh.cells_dict["triangle"]
    tets = mesh.cells_dict["tetra"]
    if not np.isfinite(points).all() or not len(tets):
        raise ValueError("expected finite coordinates and a nonempty volume mesh")
    tags = mesh.cell_data_dict.get("gmsh:physical", {})
    if set(tags) != {"triangle", "tetra"}:
        raise ValueError("missing physical boundary or volume labels")
    if set(tags["triangle"]) != {1, 2, 3}:
        raise ValueError("expected inlet/outlet/wall physical tags 1/2/3")
    if set(tags["tetra"]) != {4}:
        raise ValueError("expected fluid volume tag 4")
    for name, tag in (("inlet", 1), ("outlet", 2), ("wall", 3), ("fluid", 4)):
        dimension = 3 if name == "fluid" else 2
        if not np.array_equal(mesh.field_data.get(name), [tag, dimension]):
            raise ValueError(f"missing or inconsistent physical name: {name}")

    def face_keys(tet):
        return [tuple(sorted(tet[list(ids)])) for ids in FACE_VERTICES]

    incidence = Counter(face for tet in tets for face in face_keys(tet))
    if any(count > 2 for count in incidence.values()):
        raise ValueError("non-manifold volume face")
    boundary = {face for face, count in incidence.items() if count == 1}
    listed = Counter(tuple(sorted(tri)) for tri in triangles)
    if set(listed) != boundary or any(count != 1 for count in listed.values()):
        raise ValueError("surface must list the volume exterior exactly once")

    def signed_six_volumes(coordinates, connectivity):
        xyz = coordinates[connectivity]
        return np.einsum("ij,ij->i", np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]),
                         xyz[:, 3] - xyz[:, 0])

    original_signed = signed_six_volumes(points, tets)
    if np.any(original_signed == 0.0):
        raise ValueError("zero-volume input tetrahedron")
    split_ids = [i for i, tet in enumerate(tets)
                 if sum(face in boundary for face in face_keys(tet)) >= 2]
    split_set = set(split_ids)
    output_points = list(points)
    output_tets = []
    for i, tet in enumerate(tets):
        if i in split_set:
            center_id = len(output_points)
            output_points.append(points[tet].mean(axis=0))
            output_tets.extend([*(int(tet[j]) for j in ids), center_id]
                               for ids in FACE_VERTICES)
        else:
            output_tets.append(list(map(int, tet)))
    output_points = np.asarray(output_points)
    output_tets = np.asarray(output_tets)
    signed = signed_six_volumes(output_points, output_tets)
    if np.any(signed == 0.0):
        raise ValueError("zero-volume output tetrahedron")
    inverted = signed < 0.0
    output_tets[inverted, :2] = output_tets[inverted, :2][:, ::-1]
    original_volume = float(np.abs(original_signed).sum() / 6.0)
    output_volume = float(np.abs(signed).sum() / 6.0)
    relative_change = abs(output_volume - original_volume) / original_volume
    if relative_change > 1.0e-12:
        raise ValueError("volume changed during center subdivision")
    output_incidence = Counter(face for tet in output_tets for face in face_keys(tet))
    output_boundary = {face for face, count in output_incidence.items() if count == 1}
    if output_boundary != boundary or any(count > 2 for count in output_incidence.values()):
        raise ValueError("subdivision changed the external boundary or face conformity")
    remaining = sum(sum(face in output_boundary for face in face_keys(tet)) >= 2
                    for tet in output_tets)
    if remaining:
        raise ValueError("cells with multiple external faces remain")
    out_tags = [tags["triangle"], np.full(len(output_tets), 4, dtype=int)]
    output = meshio.Mesh(output_points, [("triangle", triangles), ("tetra", output_tets)],
                         cell_data={"gmsh:physical": out_tags, "gmsh:geometrical": out_tags},
                         field_data=mesh.field_data)
    meshio.write(target, output, file_format="gmsh22", binary=False)
    report = {
        "status": "implemented_requires_openfoam_check",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "input_cells": len(tets), "output_cells": len(output_tets),
        "split_cells": len(split_ids), "split_cell_indices": split_ids,
        "original_volume_m3": original_volume, "output_volume_m3": output_volume,
        "relative_volume_change": relative_change,
        "original_boundary_points_unchanged": bool(np.array_equal(output_points[:len(points)], points)),
        "boundary_faces_and_tags_unchanged": True,
        "nonmanifold_faces": 0, "cells_with_multiple_boundary_faces_remaining": remaining,
    }
    target.with_suffix(".repair.json").write_text(json.dumps(report, indent=2) + "\n", encoding="ascii")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    if args.source.resolve() == args.target.resolve() or args.target.exists():
        parser.error("use a new output path; input and previous results are preserved")
    print(json.dumps(repair(args.source, args.target), indent=2))


if __name__ == "__main__":
    main()
