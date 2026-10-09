"""Read-only, local diagnosis of rounded OpenFOAM self-intersection hits.

Spatial buckets are filtered by actual cell bounds. All arithmetic uses
double precision and local millimetres. Expected shared-edge/vertex contact
is separated from overlap beyond that contact; no geometry acceptance is
inferred from a local search or from floating-point predicates.
"""
from __future__ import annotations

import argparse
from collections import Counter
from itertools import combinations
from pathlib import Path
import time

import numpy as np
import vtk
from shapely.geometry import Polygon, Point, LineString

from build_scope_evidence import edge_components
from ct_case_pipeline import read_json, sha256, write_json
from export_candidate_preview import set_triangle_arrays, triangle_arrays
from surface_to_case import parse_stl_ascii


PATCHES = ("wall", "nostril_L", "nostril_R", "nasopharynx_outlet")
TOL_MM = 1e-9
AREA_TOL_MM2 = 1e-12
# OpenFOAM OBJ is printed to six significant digits. At the coordinates in
# these cases (< 1 m), rounding error is <= 0.5 micrometres on each axis.
RADIUS_M = 6e-7


def read_hits(path):
    hits = np.array([[float(x) for x in line.split()[1:]]
                     for line in path.read_text().splitlines() if line.startswith('v ')])
    if hits.size == 0:
        return np.empty((0, 3))
    if hits.ndim != 2 or hits.shape[1] != 3 or not np.isfinite(hits).all():
        raise ValueError('Expected finite OBJ vertex triples')
    return hits


def load_triangles(case_dir):
    chunks, labels = [], []
    for patch in PATCHES:
        path = case_dir / (patch + '.stl')
        if path.is_file():
            xyz = np.asarray(parse_stl_ascii(path)[patch], dtype=float)
            if xyz.ndim != 3 or xyz.shape[1:] != (3, 3) or not np.isfinite(xyz).all():
                raise ValueError('Expected finite STL triangles')
            chunks.append(xyz)
            labels.extend([patch] * len(xyz))
    if not chunks:
        raise ValueError('No known patch STL files')
    return np.concatenate(chunks), np.asarray(labels, dtype=object)


def triangle_metrics(triangle_m):
    xyz = triangle_m * 1000
    lengths = np.linalg.norm(xyz - np.roll(xyz, 1, axis=0), axis=1)
    area = float(np.linalg.norm(np.cross(xyz[1] - xyz[0], xyz[2] - xyz[0])) / 2)
    return {'area_mm2': area, 'minimum_edge_mm': float(lengths.min()),
            'quality_equilateral_1': float(4 * np.sqrt(3) * area / np.sum(lengths**2))}


def plane_section(xyz, distances, tol):
    result = [xyz[i] for i in range(3) if abs(distances[i]) <= tol]
    for i, j in ((0, 1), (1, 2), (2, 0)):
        if (distances[i] < -tol and distances[j] > tol) or (distances[j] < -tol and distances[i] > tol):
            result.append(xyz[i] + distances[i] / (distances[i] - distances[j]) * (xyz[j] - xyz[i]))
    return np.asarray(result).reshape(-1, 3)


def native_style_segment_query(start, end, triangle):
    """Unperturbed v1912 Moller-Trumbore arithmetic, without its octree.

    This reproduces the algebra, not C++ operation ordering or the actual
    octree-selected edge/face. It must not be called a native hit identity.
    """
    edge1, edge2 = triangle[1] - triangle[0], triangle[2] - triangle[0]
    direction = end - start
    p = np.cross(direction, edge2)
    determinant = float(np.dot(edge1, p))
    if abs(determinant) < 1e-150:
        return None
    inv = 1 / determinant
    delta = start - triangle[0]
    u = float(np.dot(delta, p) * inv)
    q = np.cross(delta, edge1)
    v = float(np.dot(direction, q) * inv)
    t = float(np.dot(edge2, q) * inv)
    tol = 1e-14  # indexedOctree default = 10 * doubleScalarSMALL
    if u < -tol or u > 1 + tol or v < -tol or u + v > 1 + tol or t < -tol or t > 1:
        return None
    scale = np.linalg.norm(edge1) * np.linalg.norm(edge2) * np.linalg.norm(direction)
    return {'point_m': (triangle[0] + u * edge1 + v * edge2).tolist(),
            'barycentric_uv': [u, v], 'segment_fraction': t,
            'determinant_m3': determinant,
            'relative_determinant': float(abs(determinant) / scale) if scale else 0.}


def pair_contact(a_mm, b_mm, tol=TOL_MM):
    """Floating-point plane sections plus GEOS planar area; not exact predicates.

    Shared coordinates are classified without excluding their triangles:
    adjacent triangles can still overlap beyond a legitimate common vertex.
    """
    origin = a_mm[0]
    a, b = np.asarray(a_mm) - origin, np.asarray(b_mm) - origin
    shared = np.array([p for p in a if np.any(np.linalg.norm(b - p, axis=1) <= tol)]).reshape(-1, 3)
    normal_a = np.cross(a[1] - a[0], a[2] - a[0])
    normal_b = np.cross(b[1] - b[0], b[2] - b[0])
    na, nb = np.linalg.norm(normal_a), np.linalg.norm(normal_b)
    if na <= 1e-20 or nb <= 1e-20:
        return {'kind': 'unresolved_degenerate', 'shared_vertices': len(shared)}
    normal_a, normal_b = normal_a / na, normal_b / nb
    da = (a - b[0]) @ normal_b
    db = (b - a[0]) @ normal_a
    base = {'shared_vertices': len(shared)}
    if (da.min() > tol or da.max() < -tol or db.min() > tol or db.max() < -tol):
        return base | {'kind': 'disjoint'}
    if np.max(np.abs(da)) <= tol and np.max(np.abs(db)) <= tol:
        axes = [i for i in range(3) if i != int(np.argmax(np.abs(normal_a)))]
        polygon_a, polygon_b = Polygon(a[:, axes]), Polygon(b[:, axes])
        region = polygon_a.intersection(polygon_b)
        area = float(region.area / abs(normal_a[int(np.argmax(np.abs(normal_a)))]))
        if area > AREA_TOL_MM2:
            return base | {'kind': 'coplanar_area_overlap', 'area_mm2': area}
        common = (LineString(shared[:2, axes]) if len(shared) >= 2 else
                  Point(shared[0, axes]) if len(shared) else None)
        # Rotated, collinear edges can be separated by roundoff in GEOS's
        # exact planar predicates. Check actual endpoint witnesses within the
        # stated fixed tolerance, so a partial shared edge is not mistaken
        # for only its shared vertex.
        witnesses = [Point(p) for p in a[:, axes] if polygon_b.distance(Point(p)) <= tol * 10]
        witnesses += [Point(p) for p in b[:, axes] if polygon_a.distance(Point(p)) <= tol * 10]
        beyond = common is not None and any(common.distance(p) > tol * 10 for p in witnesses)
        if beyond:
            return base | {'kind': 'coplanar_contact_beyond_shared', 'area_mm2': area}
        if region.is_empty:
            return base | {'kind': 'disjoint'}
        expected = common is not None and region.difference(common.buffer(tol * 10)).is_empty
        kind = ('expected_shared_edge' if expected and len(shared) >= 2 else
                'expected_shared_vertex' if expected else 'coplanar_contact_beyond_shared')
        return base | {'kind': kind, 'area_mm2': area}
    line = np.cross(normal_a, normal_b)
    length = np.linalg.norm(line)
    if length <= 1e-14:
        return base | {'kind': 'unresolved_near_parallel'}
    direction = line / length
    sa, sb = plane_section(a, da, tol), plane_section(b, db, tol)
    if not len(sa) or not len(sb):
        return base | {'kind': 'disjoint'}
    ia, ib = sa @ direction, sb @ direction
    low, high = max(ia.min(), ib.min()), min(ia.max(), ib.max())
    if high < low - tol:
        return base | {'kind': 'disjoint'}
    anchor = sa[0] - np.dot(sa[0], direction) * direction
    endpoints = anchor + np.array([low, high])[:, None] * direction
    if len(shared) >= 2:
        edge = shared[1] - shared[0]
        t = np.clip((endpoints - shared[0]) @ edge / np.dot(edge, edge), 0, 1)
        distance = np.linalg.norm(endpoints - (shared[0] + t[:, None] * edge), axis=1).max()
        expected = distance <= tol * 10
    elif len(shared) == 1:
        expected = np.linalg.norm(endpoints - shared[0], axis=1).max() <= tol * 10
    else:
        expected = False
    if expected:
        kind = 'expected_shared_edge' if len(shared) >= 2 else 'expected_shared_vertex'
    else:
        kind = 'crossing_beyond_shared_contact' if high - low > tol else 'nonadjacent_point_contact'
    return base | {'kind': kind, 'segment_length_mm': float(max(0, high - low)),
                   'endpoints_lps_mm': (endpoints + origin).tolist()}


def locate(case_dir, radius_m=RADIUS_M, coordinate_mode='source_double'):
    if coordinate_mode not in ('source_double', 'native_stl_float32'):
        raise ValueError('Unknown coordinate mode')
    if not np.isfinite(radius_m) or radius_m <= 0:
        raise ValueError('Expected a finite positive search radius')
    started = time.monotonic()
    paths = [case_dir / name for name in ('manifest.json', 'combined.stl', 'selfInterPoints.obj')]
    paths += [case_dir / (name + '.stl') for name in PATCHES if (case_dir / (name + '.stl')).is_file()]
    hashes = {p.name: sha256(p) for p in paths}
    manifest = read_json(case_dir / 'manifest.json')
    if hashes['combined.stl'] != manifest['combined_sha256']:
        raise ValueError('Combined STL identity mismatch')
    if hashes['selfInterPoints.obj'] != manifest['surface_check']['intersection_points_sha256']:
        raise ValueError('Native hit identity mismatch')
    triangles, patches = load_triangles(case_dir)
    for name, record in manifest['patches'].items():
        if hashes[name + '.stl'] != record['sha256'] or np.count_nonzero(patches == name) != record['triangles']:
            raise ValueError('Patch identity mismatch')
    hits = read_hits(case_dir / 'selfInterPoints.obj')
    if len(hits) != manifest['surface_check']['interpretation']['edge_triangle_intersection_hits']:
        raise ValueError('Hit count differs from native log')
    input_triangles = triangles
    if coordinate_mode == 'native_stl_float32':
        triangles = triangles.astype(np.float32).astype(np.float64)
    precision = {'mode': coordinate_mode,
                 'maximum_input_coordinate_change_m': float(np.max(np.abs(triangles - input_triangles)))}
    # Reconstruct coordinate topology, retaining every component.
    vertices, inverse = np.unique(triangles.reshape(-1, 3), axis=0, return_inverse=True)
    faces = inverse.reshape(-1, 3)
    count, components = edge_components(faces)
    native_vtp = case_dir / 'combined.vtp'
    if coordinate_mode == 'native_stl_float32' and native_vtp.is_file():
        vtp_hash = sha256(native_vtp)
        reader = vtk.vtkXMLPolyDataReader()
        reader.SetFileName(str(native_vtp.resolve()))
        reader.Update()
        native_points, native_faces = triangle_arrays(reader.GetOutput())
        native_unique = np.unique(native_points, axis=0)
        if not np.array_equal(native_unique, vertices) or len(native_faces) != len(triangles):
            raise ValueError('Float32 reconstruction differs from actual native VTP output')
        precision['native_vtp_vertex_set_match'] = True
        precision['native_vtp_sha256'] = vtp_hash
    poly = vtk.vtkPolyData()
    set_triangle_arrays(poly, vertices.astype(np.float64), faces)
    if poly.GetPoints().GetDataType() != vtk.VTK_DOUBLE:
        raise ValueError('Locator must preserve double precision')
    locator = vtk.vtkStaticCellLocator()
    locator.SetDataSet(poly)
    locator.BuildLocator()
    cell_min, cell_max = triangles.min(axis=1), triangles.max(axis=1)
    results, cache = [], {}
    suspicious = {'coplanar_area_overlap', 'crossing_beyond_shared_contact',
                  'coplanar_contact_beyond_shared', 'nonadjacent_point_contact'}
    for index, point in enumerate(hits):
        if np.any(np.abs(point) >= 1):
            raise ValueError('Rounding bound validated only for coordinates below 1 metre')
        ids = vtk.vtkIdList()
        low, high = point - radius_m, point + radius_m
        locator.FindCellsWithinBounds(np.column_stack((low, high)).ravel(), ids)
        broad = np.array([ids.GetId(i) for i in range(ids.GetNumberOfIds())], dtype=int)
        selected = broad[((cell_max[broad] >= low) & (cell_min[broad] <= high)).all(axis=1)]
        pair_ids, expected, disjoint = [], Counter(), 0
        for left, right in combinations(sorted(selected.tolist()), 2):
            key = (left, right)
            if key not in cache:
                cache[key] = pair_contact(triangles[left] * 1000, triangles[right] * 1000)
            result = cache[key]
            if result['kind'].startswith('expected_'):
                expected[result['kind']] += 1
            elif result['kind'] == 'disjoint':
                disjoint += 1
            else:
                pair_ids.append([left, right])
        edge_sources = {}
        for source_face in selected:
            for a, b in ((0, 1), (1, 2), (2, 0)):
                key = tuple(sorted((int(faces[source_face, a]), int(faces[source_face, b]))))
                edge_sources.setdefault(key, []).append(int(source_face))
        edge_matches = []
        for edge, source_faces in edge_sources.items():
            for target in selected:
                if np.isin(faces[target], edge).any():
                    continue
                for direction in (edge, edge[::-1]):
                    query = native_style_segment_query(vertices[direction[0]], vertices[direction[1]], triangles[target])
                    if query and np.max(np.abs(np.asarray(query['point_m']) - point)) <= radius_m:
                        edge_matches.append({'edge_vertices': list(direction), 'source_triangles': source_faces,
                                             'target_triangle': int(target),
                                             'source_patch_names': [str(patches[i]) for i in source_faces],
                                             'target_patch': str(patches[target]),
                                             'contact_kinds': [pair_contact(triangles[i] * 1000, triangles[target] * 1000)['kind'] for i in source_faces],
                                             **query})
        closest, cell, sub, dist = [0., 0., 0.], vtk.reference(0), vtk.reference(0), vtk.reference(0.)
        locator.FindClosestPoint(point, closest, cell, sub, dist)
        results.append({'hit_index': index, 'point_lps_m': point.tolist(),
                        'bucket_candidate_count': len(broad), 'bounded_candidate_count': len(selected),
                        'candidate_triangles': selected.tolist(), 'nearest_triangle': int(cell),
                        'nearest_distance_m': float(dist)**.5, 'expected_contact_counts': dict(expected),
                        'disjoint_pairs': disjoint, 'nontrivial_pairs': pair_ids,
                        'unperturbed_native_style_edge_matches': edge_matches,
                        'status': 'local_suspicious_contact' if any(cache[tuple(k)]['kind'] in suspicious for k in pair_ids)
                                  else 'native_hit_unresolved'})
    pairs = []
    for (left, right), result in cache.items():
        if result['kind'].startswith('expected_') or result['kind'] == 'disjoint':
            continue
        pairs.append({'triangles': [left, right], 'patches': [str(patches[left]), str(patches[right])],
                      'components': [int(components[left]), int(components[right])],
                      'vertices_lps_mm': (triangles[[left, right]] * 1000).tolist(), **result})
    if any(sha256(p) != hashes[p.name] for p in paths):
        raise ValueError('Inputs changed during diagnosis')
    if 'native_vtp_sha256' in precision and sha256(native_vtp) != precision['native_vtp_sha256']:
        raise ValueError('Native VTP changed during diagnosis')
    candidate_ids = (np.unique(np.concatenate([r['candidate_triangles'] for r in results])).astype(int)
                     if results else np.empty(0, dtype=int))
    candidates = [{'triangle': int(i), 'patch': str(patches[i]), 'component': int(components[i]),
                   'vertices_lps_m': triangles[i].tolist(), 'metrics': triangle_metrics(triangles[i])}
                  for i in candidate_ids]
    return {'schema': 'surface_intersection_localization/v3', 'input_hashes': hashes,
            'generator_sha256': sha256(Path(__file__)), 'case_dir': str(case_dir),
            'precision': precision,
            'triangle_id_order': 'zero based; known patch order, original per-patch STL order',
            'coordinate_system': 'LPS', 'unit': 'm; contact predicates use centred mm',
            'radius_m': radius_m, 'predicate_tolerance_mm': TOL_MM,
            'coplanar_area_tolerance_mm2': AREA_TOL_MM2, 'triangle_count': len(triangles),
            'component_count': int(count), 'hit_count': len(hits),
            'unique_pair_count': len(cache), 'pair_kind_counts': dict(Counter(v['kind'] for v in cache.values())),
            'hits_with_suspicious_contact': sum(r['status'] == 'local_suspicious_contact' for r in results),
            'unresolved_native_hits': sum(r['status'] == 'native_hit_unresolved' for r in results),
            'hits_with_unperturbed_native_style_match': sum(bool(r['unperturbed_native_style_edge_matches']) for r in results),
            'candidate_patch_counts': dict(Counter(patches[candidate_ids].tolist())),
            'candidate_triangles': candidates,
            'pairs': pairs, 'hits': results, 'elapsed_seconds': time.monotonic() - started,
            'limitations': ['Local rounded-hit search, not exhaustive surface intersection coverage',
                            'Floating-point plane sections and GEOS predicates, not exact arithmetic',
                            'Algebraic edge queries do not reproduce native octree traversal or identify its exact selected edge/face',
                            'No absence of local overlap may override the native failed preflight'],
            'all_components_retained': True, 'volume_mesh_generated': False,
            'patient_solver_allowed': False, 'patient_cfd_results': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--coordinate-mode', choices=('source_double', 'native_stl_float32'), default='source_double')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Preserve earlier diagnosis; use a new output directory')
    args.output.mkdir(parents=True)
    records = []
    for case in ('p2_source', 'p2', 'p3t1_source', 'p3t1'):
        report = locate(args.preflight / case, coordinate_mode=args.coordinate_mode)
        write_json(args.output / (case + '.json'), report)
        summary = {k: v for k, v in report.items() if k not in ('pairs', 'hits', 'candidate_triangles')}
        records.append({'case': case, **summary, 'report_sha256': sha256(args.output / (case + '.json'))})
        print(case, report['pair_kind_counts'], 'unresolved:', report['unresolved_native_hits'], flush=True)
    write_json(args.output / 'summary.json', {'cases': records, 'patient_solver_allowed': False, 'patient_cfd_results': 0})


if __name__ == '__main__':
    main()
