"""Convert a Netgen VOL with explicit face semantics and units to Gmsh 2.2.

No geometry generation, medical approval, repair, or solver is performed.
Face descriptors are geometry-specific and must never be inferred from order.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import meshio
import numpy as np

from repair_boundary_tetrahedra import BOUNDARY_LAYOUTS, FACE_VERTICES


def integer_array(value, name):
    array = np.asarray(value)
    if array.dtype.kind not in "iu":
        raise ValueError(f"{name} must contain integer indices")
    return array.astype(np.int64)


def convert_arrays(points, triangles, descriptors, tetrahedra, mapping, profile, unit):
    if profile not in BOUNDARY_LAYOUTS:
        raise ValueError("unknown boundary profile")
    layout = BOUNDARY_LAYOUTS[profile]
    if unit not in {"mm", "m"}:
        raise ValueError("input unit must be mm or m")
    points = np.asarray(points, dtype=float) * (0.001 if unit == "mm" else 1.0)
    triangles = integer_array(triangles, "triangles")
    tetrahedra = integer_array(tetrahedra, "tetrahedra")
    descriptors = integer_array(descriptors, "descriptors")
    if (points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all()
            or not len(points) or triangles.ndim != 2 or triangles.shape[1] != 3
            or not len(triangles) or tetrahedra.ndim != 2 or tetrahedra.shape[1] != 4
            or not len(tetrahedra) or descriptors.shape != (len(triangles),)):
        raise ValueError("expected finite 3D points, linear triangles and tetrahedra")
    for cells in (triangles, tetrahedra):
        if cells.min() < 0 or cells.max() >= len(points):
            raise ValueError("connectivity index outside points")
    if not isinstance(mapping, dict) or any(
            type(key) is not int or key <= 0 or not isinstance(value, str)
            for key, value in mapping.items()):
        raise ValueError("mapping must use positive integer descriptors and patch names")
    if (set(mapping) != set(descriptors.tolist())
            or set(mapping.values()) != set(layout) - {"fluid"}):
        raise ValueError("mapping must cover every descriptor and every boundary exactly")
    incidence = Counter(tuple(sorted(tet[list(ids)]))
                        for tet in tetrahedra for ids in FACE_VERTICES)
    exterior = {face for face, count in incidence.items() if count == 1}
    listed = Counter(tuple(sorted(tri)) for tri in triangles)
    if (any(count > 2 for count in incidence.values()) or set(listed) != exterior
            or any(count != 1 for count in listed.values())):
        raise ValueError("surface must list the manifold volume exterior exactly once")
    xyz = points[tetrahedra]
    signed = np.einsum("ij,ij->i", np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]),
                       xyz[:, 3] - xyz[:, 0])
    if not np.isfinite(signed).all() or np.any(signed == 0):
        raise ValueError("zero or nonfinite tetrahedron volume")
    tetrahedra = tetrahedra.copy()
    tetrahedra[signed < 0, :2] = tetrahedra[signed < 0, :2][:, ::-1]
    surface_tags = np.array([layout[mapping[d]] for d in descriptors])
    tags = [surface_tags, np.full(len(tetrahedra), layout["fluid"], dtype=int)]
    mesh = meshio.Mesh(points, [("triangle", triangles), ("tetra", tetrahedra)],
                       cell_data={"gmsh:physical": tags, "gmsh:geometrical": tags},
                       field_data={name: [tag, 3 if name == "fluid" else 2]
                                   for name, tag in layout.items()})
    return mesh, {"input_unit": unit, "output_unit": "m", "physical_layout": layout,
                  "descriptor_mapping": mapping, "points": len(points),
                  "tetrahedra": len(tetrahedra), "volume_m3": float(np.abs(signed).sum() / 6),
                  "patch_triangle_counts": dict(Counter(mapping[d] for d in descriptors)),
                  "status": "converted_requires_repair_and_openfoam_check",
                  "medical_approval_granted": False, "patient_solver_allowed": False}


def read_vol(source):
    from netgen.meshing import Mesh
    mesh = Mesh()
    mesh.Load(str(source))
    points = [list(point.p) for point in mesh.Points()]
    faces, cells = list(mesh.Elements2D()), list(mesh.Elements3D())
    return (points, [[point.nr - 1 for point in element.points] for element in faces],
            [element.index for element in faces],
            [[point.nr - 1 for point in element.points] for element in cells])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path, nargs="?")
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--mapping", type=Path, help='JSON object: {"descriptor": "patch"}')
    parser.add_argument("--profile", choices=tuple(BOUNDARY_LAYOUTS))
    parser.add_argument("--input-unit", choices=("mm", "m"))
    args = parser.parse_args(argv)
    if not args.inspect:
        if args.target is None or args.mapping is None or args.profile is None or args.input_unit is None:
            parser.error("conversion requires target, --mapping, --profile and --input-unit")
        if args.target.exists() or args.target.with_suffix(".conversion.json").exists():
            parser.error("use a new output path; previous results are preserved")
    arrays = read_vol(args.source)
    if args.inspect:
        print(json.dumps({"source": str(args.source), "descriptor_triangle_counts":
                          dict(Counter(arrays[2])), "semantics_inferred": False}, indent=2))
        return 0
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate descriptor in mapping JSON")
            result[key] = value
        return result
    raw = json.loads(args.mapping.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    if not isinstance(raw, dict):
        raise ValueError("mapping JSON must be an object")
    mapping = {int(key): value for key, value in raw.items()}
    if len(mapping) != len(raw):
        raise ValueError("duplicate descriptor after integer normalization")
    mesh, report = convert_arrays(*arrays, mapping, args.profile, args.input_unit)
    meshio.write(args.target, mesh, file_format="gmsh22", binary=False)
    report.update({"source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
                   "mapping_sha256": hashlib.sha256(args.mapping.read_bytes()).hexdigest(),
                   "output_sha256": hashlib.sha256(args.target.read_bytes()).hexdigest()})
    args.target.with_suffix(".conversion.json").write_text(json.dumps(report, indent=2) + "\n",
                                                         encoding="ascii")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
