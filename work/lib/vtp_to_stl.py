# -*- coding: utf-8 -*-
"""Export an opening-stage surface (auto_placed.vtp) to an ASCII STL that a
mesh generator can still read as four named boundary patches.

Two constraints learned the hard way (2026-10-13), both about *silent* failures:

1. The Netgen build used here reads a **binary STL as ZERO triangles without
   raising**. A green-looking run produces an empty mesh. So the STL is written
   in ASCII.
2. If the ASCII STL is one undifferentiated `solid` block, Netgen assigns a
   separate surface descriptor to essentially every triangle (11,140 of them on
   the first attempt). Grouping the facets into one `solid <patch>` section per
   boundary is what makes the geometry come back as four meaningful patches -
   the same shape the round-tube control had (solid inlet / outlet / wall).

The patch areas are also written to the report. They are the *known answers*
used to verify, after meshing, that descriptor N really is the patch we think
it is. Descriptor order is recorded but never trusted on its own.

Units: auto_placed.vtp coordinates are millimetres; the STL is millimetres too.

Usage:
  python vtp_to_stl.py <auto_placed.vtp> <out.stl> [--report out.json]
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path

import vtk

PATCH_ORDER = ('nostril_L', 'nostril_R', 'nasopharynx_outlet', 'wall')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def collect(poly):
    """Group triangle vertex coordinates and areas by boundary patch."""
    cd = poly.GetCellData()
    arr = cd.GetAbstractArray('boundary_patch')
    if arr is None:
        raise SystemExit('no boundary_patch cell array - refusing to export a '
                         'surface whose openings carry no semantics')
    names = {arr.GetValue(i) for i in range(poly.GetNumberOfCells())}
    unknown = names - set(PATCH_ORDER)
    if unknown:
        raise SystemExit(f'unknown patch names in surface: {sorted(unknown)}; '
                         f'expected a subset of {list(PATCH_ORDER)}')
    pts = poly.GetPoints()
    tris = collections.defaultdict(list)
    areas = collections.defaultdict(float)
    for i in range(poly.GetNumberOfCells()):
        ids = poly.GetCell(i).GetPointIds()
        a = [pts.GetPoint(ids.GetId(k)) for k in range(3)]
        u = [a[1][k] - a[0][k] for k in range(3)]
        v = [a[2][k] - a[0][k] for k in range(3)]
        cx = u[1] * v[2] - u[2] * v[1]
        cy = u[2] * v[0] - u[0] * v[2]
        cz = u[0] * v[1] - u[1] * v[0]
        n = (cx * cx + cy * cy + cz * cz) ** 0.5
        areas[arr.GetValue(i)] += 0.5 * n
        unit = (cx / n, cy / n, cz / n) if n else (0.0, 0.0, 0.0)
        tris[arr.GetValue(i)].append((unit, a))
    return tris, areas


def write_ascii_stl(tris, path):
    """One `solid <name>` section per patch, in PATCH_ORDER."""
    missing = [p for p in PATCH_ORDER if p not in tris]
    if missing:
        raise SystemExit(f'surface is missing patch(es) {missing}; every '
                         'boundary of the nasal geometry must be present')
    with open(path, 'w', encoding='ascii', newline='\n') as out:
        for name in PATCH_ORDER:
            out.write(f'solid {name}\n')
            for normal, verts in tris[name]:
                out.write(f' facet normal {normal[0]:.17g} {normal[1]:.17g} '
                          f'{normal[2]:.17g}\n  outer loop\n')
                for v in verts:
                    out.write(f'   vertex {v[0]:.17g} {v[1]:.17g} '
                              f'{v[2]:.17g}\n')
                out.write('  endloop\n endfacet\n')
            out.write(f'endsolid {name}\n')


def patch_planes(tris):
    """Point and unit normal per patch, by Newell's method.

    The three openings are planar caps, so their plane is a stable, checkable
    description: after meshing, a boundary face belongs to an opening iff its
    vertices lie on that plane. That is what replaces the mesh generator's own
    surface segmentation, which fragments a dense organic wall into thousands
    of meaningless pieces.
    """
    planes = {}
    for name, facets in tris.items():
        nx = ny = nz = 0.0
        cx = cy = cz = 0.0
        m = 0
        for _, v in facets:
            for i in range(3):
                a, b = v[i], v[(i + 1) % 3]
                nx += (a[1] - b[1]) * (a[2] + b[2])
                ny += (a[2] - b[2]) * (a[0] + b[0])
                nz += (a[0] - b[0]) * (a[1] + b[1])
            cx += sum(p[0] for p in v) / 3.0
            cy += sum(p[1] for p in v) / 3.0
            cz += sum(p[2] for p in v) / 3.0
            m += 1
        norm = (nx * nx + ny * ny + nz * nz) ** 0.5
        if norm == 0.0:
            raise SystemExit(f'patch {name} has degenerate geometry; cannot '
                             'define a plane from it')
        planes[name] = {'point': [cx / m, cy / m, cz / m],
                        'normal': [nx / norm, ny / norm, nz / norm]}
    return planes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source')
    ap.add_argument('out')
    ap.add_argument('--report', default=None)
    args = ap.parse_args()

    src = Path(args.source)
    reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(str(src))
    reader.Update()
    poly = reader.GetOutput()

    tris, areas = collect(poly)
    write_ascii_stl(tris, args.out)
    bounds = poly.GetBounds()

    report = {
        'source': str(src),
        'source_sha256': sha256(src),
        'stl': str(args.out),
        'stl_sha256': sha256(Path(args.out)),
        'stl_encoding': 'ascii',
        'units': 'mm',
        'points': poly.GetNumberOfPoints(),
        'triangles': poly.GetNumberOfCells(),
        'solid_section_order': list(PATCH_ORDER),
        'patch_areas_mm2': {k: round(v, 6) for k, v in sorted(areas.items())},
        'patch_triangle_counts': {k: len(tris[k]) for k in sorted(tris)},
        'patch_planes': patch_planes(tris),
        'bbox_mm': {'x': [bounds[0], bounds[1]], 'y': [bounds[2], bounds[3]],
                    'z': [bounds[4], bounds[5]]},
        'note': 'patch_areas_mm2 are the anchors used to verify the mesh '
                "generator's surface descriptor mapping. solid_section_order "
                'records the order written, but the mapping must still be '
                'confirmed against the areas - never inferred from index. '
                'patch_planes is meaningful ONLY for the three planar caps; the '
                'wall is curved, so its Newell normal is not a surface '
                'description and no area is derived from it.',
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding='utf-8')


if __name__ == '__main__':
    main()
