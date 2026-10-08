"""Validated planar caps in LPS millimetres, including nested contours.

This engineering component does not approve anatomy or authorize patient CFD.
GEOS triangulates shells with their holes; no fan fallback is permitted.
"""
from collections import Counter

import numpy as np
import shapely
from shapely import Polygon, Point, MultiPolygon, constrained_delaunay_triangles
import vtk


def triangulate_cap(vertices, loops, normal, *, tolerance_mm=1e-6):
    """Return original vertex-index triangles and technical QC, never approval.

    Loops must be disjoint, simple, coplanar and use distinct vertex IDs; their
    winding is normalized by nesting depth. Collinear boundary points remain
    mandatory: the cap must share every boundary edge with the clipped wall.
    """
    points = np.asarray(vertices, dtype=float)
    direction = np.asarray(normal, dtype=float)
    if (points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all()
            or direction.shape != (3,) or not np.isfinite(direction).all()
            or np.linalg.norm(direction) < 1e-12
            or not np.isfinite(tolerance_mm) or tolerance_mm <= 0):
        raise ValueError('Invalid vertices, normal or tolerance')
    direction = direction / np.linalg.norm(direction)
    contours = []
    for loop in loops:
        ids = np.asarray(loop)
        if (ids.ndim != 1 or ids.dtype.kind not in 'iu' or len(ids) < 3
                or len(set(ids.tolist())) != len(ids) or np.any(ids < 0) or np.any(ids >= len(points))):
            raise ValueError('Invalid contour vertex IDs')
        contours.append(ids.astype(np.int64))
    if not contours:
        raise ValueError('No contours')
    used = np.concatenate(contours)
    if len(set(used.tolist())) != len(used):
        raise ValueError('Contours share vertices')
    origin = points[used[0]]
    if np.max(np.abs((points[used] - origin) @ direction)) > tolerance_mm:
        raise ValueError('Contours are not coplanar')

    # Reject crossing, touching and collapsed boundaries before triangulation.
    edges = [(int(a), int(b)) for ids in contours for a, b in zip(ids, np.roll(ids, -1))]
    for index, (a, b) in enumerate(edges):
        if np.linalg.norm(points[a] - points[b]) <= tolerance_mm:
            raise ValueError('Collapsed boundary edge')
        for c, d in edges[index + 1:]:
            if {a, b} & {c, d}:
                continue
            lo = np.maximum(np.minimum(points[a], points[b]), np.minimum(points[c], points[d]))
            hi = np.minimum(np.maximum(points[a], points[b]), np.maximum(points[c], points[d]))
            if np.any(lo > hi + tolerance_mm):
                continue
            t1, t2 = vtk.reference(0.0), vtk.reference(0.0)
            p1, p2 = [0.0] * 3, [0.0] * 3
            distance2 = vtk.vtkLine.DistanceBetweenLineSegments(
                points[a], points[b], points[c], points[d], p1, p2, t1, t2)
            if distance2 <= tolerance_mm ** 2:
                raise ValueError('Contours cross or touch')

    # Triangulate in a centered local plane, retaining original point IDs.
    first = points[contours[0]]
    vectors = np.roll(first, -1, axis=0) - first
    vectors -= (vectors @ direction)[:, None] * direction
    axis_u = vectors[np.argmax(np.linalg.norm(vectors, axis=1))].copy()
    axis_u /= np.linalg.norm(axis_u)
    axis_v = np.cross(direction, axis_u)
    projected = points - (origin + (points[used] - origin).mean(axis=0))
    projected = np.column_stack((projected @ axis_u, projected @ axis_v))
    polygons = [Polygon(projected[loop]) for loop in contours]
    if any(not polygon.is_valid for polygon in polygons):
        raise ValueError('Contours cross or touch')
    if any(polygon.area <= tolerance_mm ** 2 for polygon in polygons):
        raise ValueError('Zero-area contour')
    contained = [[other.contains(Point(projected[loop[0]])) if j != i else False
                  for j, other in enumerate(polygons)] for i, loop in enumerate(contours)]
    depths = [sum(row) for row in contained]
    regions = [Polygon(projected[loop], [projected[contours[j]] for j in range(len(contours))
               if depths[j] == depths[i] + 1 and contained[j][i]])
               for i, loop in enumerate(contours) if depths[i] % 2 == 0]
    domain = MultiPolygon(regions)
    if not domain.is_valid or domain.area <= tolerance_mm ** 2:
        raise ValueError('Invalid nested contour domain')
    expected = domain.area
    point_ids = {tuple(projected[index]): int(index) for index in used}
    if len(point_ids) != len(used):
        raise ValueError('Contours share projected vertices')
    faces = []
    triangle_polygons = []
    for region in regions:
        for triangle in constrained_delaunay_triangles(region).geoms:
            coordinates = list(triangle.exterior.coords)[:-1]
            if len(coordinates) != 3:
                raise ValueError('Triangulator returned a non-triangle')
            if not all(tuple(point) in point_ids for point in coordinates):
                raise ValueError('Triangulator changed boundary vertices')
            faces.append([point_ids[tuple(point)] for point in coordinates])
            triangle_polygons.append(triangle)
    if not faces:
        raise ValueError('Empty cap')
    if not all(domain.covers(triangle) for triangle in triangle_polygons):
        raise ValueError('Triangle fills a hole or lies outside contours')
    union = shapely.union_all(triangle_polygons)
    area_tolerance = max(expected * 1e-9, tolerance_mm ** 2)
    if (domain.symmetric_difference(union).area > area_tolerance
            or abs(sum(triangle.area for triangle in triangle_polygons) - union.area) > area_tolerance):
        raise ValueError('Cap coverage has gaps or overlapping triangles')
    triangles = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if not len(triangles) or not set(triangles.ravel()).issubset(set(used)):
        raise ValueError('Empty cap or unexpected vertices')
    cross = np.cross(points[triangles[:, 1]] - points[triangles[:, 0]],
                     points[triangles[:, 2]] - points[triangles[:, 0]])
    signs = cross @ direction
    if np.any(np.abs(signs) <= tolerance_mm ** 2):
        raise ValueError('Degenerate cap triangle')
    triangles[signs < 0] = triangles[signs < 0][:, [0, 2, 1]]
    area = float(np.linalg.norm(cross, axis=1).sum() * 0.5)
    perimeter = sum(np.linalg.norm(points[a] - points[b]) for a, b in edges)
    if abs(area - expected) > max(expected * 1e-9, tolerance_mm * perimeter * 4):
        raise ValueError('Cap area does not match contours minus holes')
    counts = Counter(tuple(sorted((int(a), int(b)))) for face in triangles
                     for a, b in zip(face, np.roll(face, -1)))
    expected_edges = {tuple(sorted(edge)) for edge in edges}
    if {edge for edge, count in counts.items() if count == 1} != expected_edges or any(
            count not in (1, 2) for count in counts.values()):
        raise ValueError('Cap does not preserve the exact wall boundary')
    return triangles, {
        'schema': 'planar_cap_qc/v1', 'method': 'GEOS constrained Delaunay triangulation',
        'shapely_version': shapely.__version__, 'geos_version': shapely.geos_version_string,
        'vtk_version': vtk.vtkVersion.GetVTKVersion(), 'coordinate_system': 'LPS', 'unit': 'mm',
        'area_mm2': area, 'expected_area_mm2': expected, 'contour_depths': depths,
        'boundary_edges': len(edges), 'triangle_count': len(triangles),
        'technical_checks_passed': True, 'patient_solver_allowed': False,
    }
