"""Exact finite-ROI plane clips and labelled caps; anatomy is never inferred.

ROI limits are selection limits, not extra cutting planes. If deleted wall
crosses an ROI boundary, stop instead of inventing lateral walls or silently
enlarging the configured ROI. Results are engineering drafts, never approval.
"""
from collections import Counter, defaultdict

import numpy as np

from planar_cap import triangulate_cap
from outlet_selection_lineage import SourceSelectorLineage


class SurfaceClipError(ValueError):
    def __init__(self, message, details):
        super().__init__(message)
        self.details = details


def topology(points, faces):
    directed = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    canonical = np.sort(directed, axis=1)
    edges, inverse, counts = np.unique(canonical, axis=0, return_inverse=True, return_counts=True)
    balance = np.bincount(inverse, weights=np.where(directed[:, 0] < directed[:, 1], 1, -1))
    triangles = points[faces]
    areas = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0],
                                    triangles[:, 2] - triangles[:, 0]), axis=1) * .5
    reference = points.mean(axis=0)
    signed_volume = float(np.einsum('ij,ij->i', triangles[:, 0] - reference,
                          np.cross(triangles[:, 1] - reference, triangles[:, 2] - reference)).sum() / 6)
    return {'boundary_edges': int(np.count_nonzero(counts == 1)),
            'nonmanifold_edges': int(np.count_nonzero(counts > 2)),
            'inconsistent_winding_edges': int(np.count_nonzero((counts == 2) & (balance != 0))),
            'duplicate_triangles': len(faces) - len(np.unique(np.sort(faces, axis=1), axis=0)),
            'degenerate_triangles': int(np.count_nonzero(areas <= 1e-12)),
            'surface_area_mm2': float(areas.sum()), 'signed_volume_mm3': signed_volume,
            'triangles': len(faces), 'vertices': len(points)}, edges[counts == 1]


def boundary_loops(edges):
    neighbors = defaultdict(list)
    for a, b in edges:
        neighbors[int(a)].append(int(b))
        neighbors[int(b)].append(int(a))
    if not neighbors or any(len(values) != 2 for values in neighbors.values()):
        raise ValueError('Cut boundaries must be closed degree-two loops')
    unused = {tuple(sorted((int(a), int(b)))) for a, b in edges}
    loops = []
    while unused:
        a, b = min(unused)
        loop = [a]
        previous, current = a, b
        unused.remove((a, b))
        while current != a:
            loop.append(current)
            nxt = next(value for value in neighbors[current] if value != previous)
            edge = tuple(sorted((current, nxt)))
            if edge not in unused:
                raise ValueError('Boundary loop revisits an edge')
            unused.remove(edge)
            previous, current = current, nxt
        if len(loop) < 3:
            raise ValueError('Collapsed boundary loop')
        loops.append(loop)
    return loops


def clip_and_cap(vertices, triangles, planes, *, tolerance_mm=1e-7, selectors=None):
    """Clip each named plane and cap it.

    `selectors` optionally maps a plane name to a boolean per-vertex mask that
    replaces the axis-aligned ROI box as the selection predicate. The box is a
    rectangular proxy that cannot represent the nasopharyngeal wall, which keeps
    extending past the box face; a connectivity-derived mask states the same
    intent without inventing lateral walls. Passing None keeps the original
    ROI-box behaviour byte for byte.

    Selectors contain exactly one boolean per source vertex and describe
    strict-delete-side connected components. New edge intersections inherit
    membership from their parents and the selector's own plane. Selection may
    not change across a wholly negative source edge. Ambiguous input is rejected
    rather than silently treating all new vertices as unselected.
    """
    if not np.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise ValueError('Tolerance must be finite and positive')
    selectors = selectors or {}
    points = np.asarray(vertices, dtype=float)
    faces = np.asarray(triangles)
    if (points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all()
            or faces.ndim != 2 or faces.shape[1] != 3 or faces.dtype.kind not in 'iu'
            or not len(faces) or faces.min() < 0 or faces.max() >= len(points)):
        raise ValueError('Expected a finite triangle mesh')
    faces = faces.astype(np.int64, copy=True)
    qc, _ = topology(points, faces)
    if any(qc[key] for key in ('boundary_edges', 'nonmanifold_edges', 'inconsistent_winding_edges',
                                'duplicate_triangles', 'degenerate_triangles')) or qc['signed_volume_mm3'] <= 0:
        raise ValueError('Source must be a closed consistently outward triangle surface')
    lineage = SourceSelectorLineage(points, faces, planes, selectors, tolerance_mm)
    patches = np.full(len(faces), 'wall', dtype=object)
    reports = {}
    for name, spec in planes.items():
        if name == 'wall' or name in reports:
            raise ValueError('Invalid patch name')
        origin = np.asarray(spec.get('point_lps_mm'), dtype=float)
        normal = np.asarray(spec.get('normal_lps'), dtype=float)
        roi = spec.get('roi_lps_mm', {})
        low, high = np.asarray(roi.get('min'), dtype=float), np.asarray(roi.get('max'), dtype=float)
        if (any(v.shape != (3,) or not np.isfinite(v).all() for v in (origin, normal, low, high))
                or np.linalg.norm(normal) < 1e-12 or np.any(low >= high)
                or type(spec.get('keep_positive')) is not bool):
            raise ValueError('Invalid clipping plane or ROI')
        normal = normal / np.linalg.norm(normal)
        kept_normal = normal if spec['keep_positive'] else -normal
        signed = (points - origin) @ kept_normal
        signed[np.abs(signed) <= tolerance_mm] = 0
        xyz = points[faces]
        mask = lineage.get(name)
        if mask is not None:
            inside = np.any(mask[faces], axis=1)
        else:
            overlap = ((xyz.max(axis=1) >= low) & (xyz.min(axis=1) <= high)).all(axis=1)
            inside = ((xyz >= low) & (xyz <= high)).all(axis=(1, 2))
            negative = np.any(signed[faces] < 0, axis=1)
            conflicts = overlap & ~inside & negative
            if np.any(conflicts):
                conflicting = xyz[conflicts]
                centers = conflicting.mean(axis=1)
                raise SurfaceClipError(name + ': deleted wall crosses the configured ROI boundary',
                                       {'plane': name, 'conflicting_triangles': int(conflicts.sum()),
                                        'triangle_centers_lps_mm': centers.tolist(),
                                        'bounds_lps_mm': {'min': conflicting.min(axis=(0, 1)).tolist(),
                                                          'max': conflicting.max(axis=(0, 1)).tolist()},
                                        'roi_lps_mm': roi})
        affected = inside & np.any(signed[faces] < 0, axis=1)
        if not affected.any():
            raise ValueError(name + ': plane does not cut the selected surface')
        if np.any(patches[affected] != 'wall'):
            collision = affected & (patches != 'wall')
            cap_points = xyz[collision]
            cap_signed = signed[faces[collision]]
            crossing = (cap_signed.min(axis=1) < 0) & (cap_signed.max(axis=1) > 0)
            raise SurfaceClipError(name + ': delete selection would remove an earlier cap',
                                   {'plane': name, 'conflicting_triangles': int(collision.sum()),
                                    'strictly_crossing_plane_triangles': int(crossing.sum()),
                                    'fully_in_delete_halfspace_triangles': int((cap_signed < 0).all(axis=1).sum()),
                                    'collision_kind': 'selection_covers_earlier_cap',
                                    'earlier_patch_counts': dict(Counter(patches[collision].tolist())),
                                    'triangle_centers_lps_mm': cap_points.mean(axis=1).tolist(),
                                    'bounds_lps_mm': {'min': cap_points.min(axis=(0, 1)).tolist(),
                                                      'max': cap_points.max(axis=(0, 1)).tolist()},
                                    'roi_lps_mm': roi})
        new_points = points.tolist()
        cache = {}

        def intersection(a, b):
            if signed[a] == 0:
                return a
            if signed[b] == 0:
                return b
            edge = tuple(sorted((a, b)))
            if edge not in cache:
                start, stop = edge
                fraction = signed[start] / (signed[start] - signed[stop])
                point = points[start] + fraction * (points[stop] - points[start])
                cache[edge] = len(new_points)
                new_points.append(point.tolist())
                lineage.append_intersection(start, stop, point)
            return cache[edge]

        output = faces[~affected].tolist()
        labels = patches[~affected].tolist()
        for face in faces[affected]:
            polygon = []
            for a, b in zip(face.tolist(), np.roll(face, -1).tolist()):
                if signed[a] >= 0:
                    polygon.append(a)
                if (signed[a] >= 0) != (signed[b] >= 0):
                    polygon.append(intersection(a, b))
            clean = []
            for index in polygon:
                if not clean or index != clean[-1]:
                    clean.append(index)
            if len(clean) > 1 and clean[0] == clean[-1]:
                clean.pop()
            for i in range(1, len(clean) - 1):
                output.append([clean[0], clean[i], clean[i + 1]])
                labels.append('wall')
        points = np.asarray(new_points, dtype=float)
        faces = np.asarray(output, dtype=np.int64).reshape(-1, 3)
        patches = np.asarray(labels, dtype=object)
        if not len(faces):
            raise ValueError(name + ': clip removes the entire surface')
        interim, edges = topology(points, faces)
        loops = boundary_loops(edges)
        used = np.unique(edges)
        outside_plane = np.max(np.abs((points[used] - origin) @ normal)) > tolerance_mm
        outside_roi = not ((points[used] >= low - tolerance_mm) &
                           (points[used] <= high + tolerance_mm)).all()
        if outside_plane or (outside_roi and mask is None):
            # With a connectivity selector the boundary legitimately leaves the
            # ROI box, so only coplanarity is enforced; the box is not the scope.
            raise ValueError(name + ': unexpected boundary outside cutting plane or ROI')
        caps, report = triangulate_cap(points, loops, -kept_normal, tolerance_mm=tolerance_mm)
        faces = np.vstack((faces, caps))
        patches = np.concatenate((patches, np.full(len(caps), name, dtype=object)))
        final, _ = topology(points, faces)
        if any(final[key] for key in ('boundary_edges', 'nonmanifold_edges',
                                      'inconsistent_winding_edges', 'degenerate_triangles', 'duplicate_triangles')):
            raise ValueError(name + ': capped surface fails topology')
        if final['signed_volume_mm3'] <= 0 or final['signed_volume_mm3'] > qc['signed_volume_mm3'] + tolerance_mm:
            raise ValueError(name + ': clipped volume is invalid or increased')
        reports[name] = report | {'loops': len(loops), 'affected_source_triangles': int(affected.sum()),
                                 'interim_boundary_edges': interim['boundary_edges']}
        qc = final
    used, inverse = np.unique(faces, return_inverse=True)
    faces = inverse.reshape(-1, 3)
    points = points[used]
    qc, _ = topology(points, faces)
    return points, faces, patches, {'schema': 'partitioned_surface_draft/v1', 'technical_qc': qc,
                                  'caps': reports, 'patch_triangle_counts': dict(Counter(patches.tolist())),
                                  'coordinate_system': 'LPS', 'unit': 'mm',
                                  'patient_solver_allowed': False, 'final_geometry_approved': False}
