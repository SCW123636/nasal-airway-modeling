"""Convert a pygalmesh MEDIT volume mesh into a tagged Gmsh 2.2 mesh.

pygalmesh/CGAL does not retain the STL solid names in its volume output.  For
the controlled cylindrical benchmark, boundary tags are reconstructed from
the z coordinate: z=0 is inlet, z=L is outlet, and the remaining triangles
are wall.  This is deliberately limited to the benchmark geometry.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import meshio
import numpy as np


def convert(source: Path, target: Path, length_mm: float = 40.0, scale: float = 0.001) -> dict[str, int]:
    mesh = meshio.read(source)
    points = np.asarray(mesh.points, dtype=float) * scale
    triangles = mesh.cells_dict["triangle"]
    tetrahedra = mesh.cells_dict["tetra"]
    if not np.isfinite(points).all() or length_mm <= 0.0 or scale <= 0.0:
        raise ValueError("expected finite points and positive benchmark dimensions")
    if points.shape[1] != 3 or len(tetrahedra) == 0:
        raise ValueError("expected a 3D tetrahedral volume mesh")
    faces = Counter(
        tuple(sorted(row[list(ids)]))
        for row in tetrahedra
        for ids in ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))
    )
    if any(count > 2 for count in faces.values()):
        raise ValueError("non-manifold tetrahedral face incidence")
    boundary = {face for face, count in faces.items() if count == 1}
    unique_triangles = {tuple(sorted(row)): row for row in triangles}
    if set(unique_triangles) != boundary:
        raise ValueError("listed surface differs from the tetrahedral exterior")
    center = points.mean(axis=0)

    def orient_face(row: np.ndarray) -> tuple[int, int, int]:
        a, b, c = map(int, row)
        normal = np.cross(points[b] - points[a], points[c] - points[a])
        face_center = (points[a] + points[b] + points[c]) / 3.0
        if float(np.dot(normal, face_center - center)) > 0.0:
            return a, b, c
        return a, c, b

    oriented_triangles = [orient_face(row) for row in unique_triangles.values()]

    def signed_volume(row: list[int]) -> float:
        a, b, c, d = points[row]
        return float(np.dot(np.cross(b - a, c - a), d - a))

    oriented_tetrahedra = []
    negative_fixed = 0
    for row in tetrahedra:
        tet = list(map(int, row))
        volume = signed_volume(tet)
        if volume == 0.0:
            raise ValueError("zero-volume tetrahedron")
        if volume < 0.0:
            tet[0], tet[1] = tet[1], tet[0]
            negative_fixed += 1
        oriented_tetrahedra.append(tet)

    end_z = length_mm * scale
    patch_counts = {"inlet": 0, "outlet": 0, "wall": 0}

    def marker(row: tuple[int, int, int]) -> int:
        z = points[list(row), 2]
        if np.all(np.abs(z) < 1.0e-8):
            patch_counts["inlet"] += 1
            return 1
        if np.all(np.abs(z - end_z) < 1.0e-8):
            patch_counts["outlet"] += 1
            return 2
        patch_counts["wall"] += 1
        return 3

    tags = [marker(row) for row in oriented_triangles]
    if not all(patch_counts.values()):
        raise ValueError("missing cylindrical inlet, outlet or wall")
    if points[:, 2].min() < -1.0e-8 or points[:, 2].max() > end_z + 1.0e-8:
        raise ValueError("mesh lies outside the controlled benchmark length")
    with target.open("w", encoding="ascii", newline="\n") as stream:
        stream.write("$MeshFormat\n2.2 0 8\n$EndMeshFormat\n")
        stream.write(
            '$PhysicalNames\n4\n2 1 "inlet"\n2 2 "outlet"\n'
            '2 3 "wall"\n3 4 "fluid"\n$EndPhysicalNames\n'
        )
        stream.write(f"$Nodes\n{len(points)}\n")
        for number, point in enumerate(points, start=1):
            stream.write("%d %.17g %.17g %.17g\n" % (number, point[0], point[1], point[2]))
        stream.write("$EndNodes\n")
        stream.write(f"$Elements\n{len(oriented_triangles) + len(oriented_tetrahedra)}\n")
        for number, (row, tag) in enumerate(zip(oriented_triangles, tags), start=1):
            stream.write("%d 2 2 %d %d %d %d %d\n" % (number, tag, tag, row[0] + 1, row[1] + 1, row[2] + 1))
        for number, row in enumerate(oriented_tetrahedra, start=len(oriented_triangles) + 1):
            stream.write("%d 4 2 4 4 %d %d %d %d\n" % (number, row[0] + 1, row[1] + 1, row[2] + 1, row[3] + 1))
        stream.write("$EndElements\n")

    result = {
        "points": len(points),
        "triangles": len(oriented_triangles),
        "tetrahedra": len(oriented_tetrahedra),
        "negative_tetrahedra_reoriented": negative_fixed,
        "duplicate_surface_triangles_removed": len(triangles) - len(oriented_triangles),
        **{f"{name}_faces": count for name, count in patch_counts.items()},
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--length-mm", type=float, default=40.0)
    args = parser.parse_args()
    print(convert(args.source, args.target, args.length_mm))


if __name__ == "__main__":
    main()
