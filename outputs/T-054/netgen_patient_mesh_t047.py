"""T-047 PATCHED COPY of work/lib/netgen_patient_mesh.py - single-variable change:
  nasopharynx_outlet -> oropharynx_truncation_outlet (all occurrences). Production file untouched.
  Original docstring follows.
Patient surface -> Netgen volume mesh -> OpenFOAM-ready .msh, with the
boundary patches recovered geometrically and then *verified against areas*.

Why not just use the mesh generator's own surface descriptors
------------------------------------------------------------
On the round-tube control, Netgen's STL reader returns one descriptor per
`solid` section, so descriptor 1/2/3 map cleanly to inlet/outlet/wall. On a
dense organic surface it does not: it grows "faces" by angle between
neighbouring triangles and returned 11,140 descriptors for this geometry,
fragmenting the three opening caps into pieces that carry no semantics. The
mapping is therefore unavailable from the descriptor numbering.

So the openings are labelled from geometry instead. Each opening is a planar
cap, and its plane comes from the exporting step; a boundary face belongs to an
opening iff its centroid lies on that plane. The result is then checked against
the boundary areas recorded by the opening stage (80.037 / 80.057 / 439.179
mm^2 for b15). A labelling that does not reproduce those areas is rejected -
this project has already shipped one gate whose output was well-formed and
wrong, and the countermeasure is to compare every new criterion against a known
answer.

The .msh is written through netgen_vol_to_msh.convert_arrays, so all of its
existing checks still apply: the surface must list the manifold volume exterior
exactly once, tetrahedra must have strictly positive volume and orientation,
and the physical-name layout must be complete.

This performs meshing only. It does not repair, solve, or assert medical
approval; the report keeps patient_solver_allowed=false.

Usage (inside WSL with netgen_env.sh sourced):
  python3 netgen_patient_mesh.py <surface.stl> <export.json> <out.msh>
      [--maxh 0.4] [--plane-tol-mm 0.05]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
import types
from pathlib import Path

import numpy as np

if 'tkinter' not in sys.modules:          # netgen imports it unconditionally
    sys.modules['tkinter'] = types.ModuleType('tkinter')

from netgen.stl import STLGeometry            # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from netgen_vol_to_msh import convert_arrays      # noqa: E402

CAPS = ('nostril_L', 'nostril_R', 'oropharynx_truncation_outlet')
MAPPING = {1: 'nostril_L', 2: 'nostril_R', 3: 'oropharynx_truncation_outlet', 4: 'wall'}


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def extract(mesh):
    """Points, boundary triangles and tetrahedra as plain 0-based arrays."""
    points = np.array([list(p.p) for p in mesh.Points()], dtype=float)
    faces = np.array([[p.nr - 1 for p in el.points] for el in mesh.Elements2D()],
                     dtype=np.int64)
    tets = np.array([[p.nr - 1 for p in el.points] for el in mesh.Elements3D()],
                    dtype=np.int64)
    return points, faces, tets


def classify(points, faces, planes, tol_mm):
    """Tag each boundary triangle by the opening plane its centroid lies on."""
    centroids = points[faces].mean(axis=1)
    tags = np.full(len(faces), 4, dtype=np.int64)                  # default: wall
    distances = np.full(len(faces), np.inf)
    for tag, name in enumerate(CAPS, start=1):
        origin = np.asarray(planes[name]['point'], dtype=float)
        normal = np.asarray(planes[name]['normal'], dtype=float)
        d = np.abs((centroids - origin) @ normal)
        take = d < tol_mm
        # a face may only belong to one opening: keep the closest plane
        better = take & (d < distances)
        tags[better] = tag
        distances[better] = d[better]
    return tags, distances


TOL_SWEEP_MM = (1e-4, 1e-3, 5e-3, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5)


def median_edge_mm(points, faces):
    """Median boundary face edge length - the local surface resolution."""
    p = points[faces]
    e = np.linalg.norm(np.stack([p[:, 1] - p[:, 0], p[:, 2] - p[:, 1],
                                 p[:, 0] - p[:, 2]], axis=1), axis=2)
    return float(np.median(e))


def area_at_tolerance(points, faces, plane, tol_mm):
    centroids = points[faces].mean(axis=1)
    origin = np.asarray(plane['point'], dtype=float)
    normal = np.asarray(plane['normal'], dtype=float)
    d = np.abs((centroids - origin) @ normal)
    sel = faces[d < tol_mm]
    if len(sel) == 0:
        return 0.0, 0
    p = points[sel]
    u, v = p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]
    return float(0.5 * np.linalg.norm(np.cross(u, v), axis=1).sum()), len(sel)


def sweep_report(points, faces, planes, anchor):
    """Label area as a function of plane tolerance, next to the known answer.

    Reported instead of a guessed tolerance: the correct threshold is the one
    at which the labelled area sits on a plateau equal to the area the opening
    stage recorded. If no such plateau exists, the plane model itself is wrong
    and no tolerance will fix it.
    """
    lines = []
    for name in CAPS:
        lines.append(f'  {name} (expected {anchor[name]:.4f} mm^2)')
        for tol in TOL_SWEEP_MM:
            area, n = area_at_tolerance(points, faces, planes[name], tol)
            mark = ''
            lines.append(f'    tol {tol:<8g} -> {area:11.4f} mm^2  ({n} faces){mark}')
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('source')
    ap.add_argument('export_json')
    ap.add_argument('target')
    ap.add_argument('--maxh', type=float, default=0.4)
    ap.add_argument('--grading', type=float, default=0.1)
    ap.add_argument('--plane-tol-frac', type=float, default=0.1,
                    help='plane tolerance as a fraction of the median boundary '
                         'face edge. Set by scale, not by fitting: the surface '
                         'optimiser displaces nodes by a small fraction of the '
                         'local edge, so the cap stops being exactly planar. The '
                         'measured residual is reported, never hidden.')
    ap.add_argument('--plane-tol-mm', type=float, default=None,
                    help='absolute override for the plane tolerance')
    ap.add_argument('--area-tol-frac', type=float, default=0.15,
                    help='gate on the labelled cap area. This guards against '
                         'MISIDENTIFICATION (one opening standing in for '
                         'another), not against rim-resolution error - the '
                         'measured deviation is always reported as a number.')
    ap.add_argument('--dump-arrays', default=None,
                    help='save points/faces/tets to this .npz so labelling can '
                         'be iterated without re-meshing')
    args = ap.parse_args(argv)

    export = json.loads(Path(args.export_json).read_text(encoding='utf-8'))
    planes = export['patch_planes']
    anchor = export['patch_areas_mm2']

    geometry = STLGeometry(str(args.source))
    mesh = geometry.GenerateMesh(maxh=args.maxh, grading=args.grading)
    points, faces, tets = extract(mesh)
    if len(points) == 0 or len(tets) == 0 or len(faces) == 0:
        raise SystemExit('empty mesh - refusing to continue (this build reads a '
                         'binary STL as zero triangles without raising)')
    if args.dump_arrays:
        np.savez_compressed(args.dump_arrays, points=points, faces=faces,
                            tets=tets, maxh=args.maxh)

    edge = median_edge_mm(points, faces)
    tol = (args.plane_tol_mm if args.plane_tol_mm is not None
           else args.plane_tol_frac * edge)
    tags, _ = classify(points, faces, planes, tol)
    areas = collections.defaultdict(float)
    counts = collections.Counter()
    for tri, tag in zip(faces, tags):
        p = points[tri]
        u, v = p[1] - p[0], p[2] - p[0]
        areas[int(tag)] += 0.5 * float(np.linalg.norm(np.cross(u, v)))
        counts[int(tag)] += 1
    labelled = {MAPPING[t]: round(areas[t], 6) for t in areas}
    deviation = {name: round((labelled.get(name, 0.0) - anchor[name])
                             / anchor[name] * 100.0, 3) for name in CAPS}

    problems = []
    for name in CAPS:
        got = labelled.get(name)
        if got is None:
            problems.append(f'{name}: no boundary face was labelled onto its '
                            'plane - the plane tolerance or the cap geometry is wrong')
            continue
        want = anchor[name]
        err = abs(got - want) / want
        if err > args.area_tol_frac:
            problems.append(
                f'{name}: labelled area {got} mm^2 differs from the opening-stage '
                f'area {want} mm^2 by {err:.1%} - beyond the misidentification '
                f'gate ({args.area_tol_frac:.0%}); this looks like the wrong '
                'region was selected, not rim-resolution error')
    if problems:
        raise SystemExit(
            'boundary labelling failed area verification:\n  - '
            + '\n  - '.join(problems)
            + '\n\nlabelled area vs plane tolerance (calibrate, do not guess):\n'
            + sweep_report(points, faces, planes, anchor)
            + ('\n\nmesh arrays saved to %s for offline diagnosis' % args.dump_arrays
               if args.dump_arrays else ''))

    mesh_out, report = convert_arrays(points, faces, tags, tets, MAPPING,
                                      'nasal', 'mm')
    import meshio
    meshio.write(args.target, mesh_out, file_format='gmsh22', binary=False)

    report.update({
        'source': str(args.source),
        'source_sha256': sha256(Path(args.source)),
        'export_json': str(args.export_json),
        'output': str(args.target),
        'output_sha256': sha256(Path(args.target)),
        'maxh': args.maxh, 'grading': args.grading,
        'plane_tol_mm': tol,
        'plane_tol_rule': (f'{args.plane_tol_frac} x median boundary face edge'
                           if args.plane_tol_mm is None else 'absolute override'),
        'median_boundary_edge_mm': round(edge, 6),
        'boundary_patch_areas_mm2': labelled,
        'boundary_patch_face_counts': {MAPPING[t]: counts[t] for t in counts},
        'opening_stage_areas_mm2': {k: anchor[k] for k in CAPS},
        'cap_area_deviation_pct': deviation,
        'cap_area_deviation_caveat': (
            'The surface optimiser bends the cap near the rim, so the cap is not '
            'exactly planar and no single plane tolerance reproduces the opening '
            'area exactly (measured, not fitted). These deviations are therefore '
            'the honest resolution of this labelling, not a precision claim; the '
            'gate only rejects misidentification.'),
        'labelling': 'geometric (centroid on the opening plane)',
        'labelling_verified_against_areas': True,
        'descriptor_semantics_used': False,
        'next_step': 'repair_boundary_tetrahedra.py then gmshToFoam + checkMesh',
    })
    print(json.dumps(report, ensure_ascii=False, indent=2))
    Path(str(args.target) + '.mesh.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
