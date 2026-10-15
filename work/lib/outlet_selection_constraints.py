"""Explicit, fingerprint-bound target loops for engineering selection trials.

Nothing picks an anatomical loop automatically. Protection/allowance constraints
are checked against whole negative components; they never trim a component to
make an off-plane cut look admissible. Final clipper/area/N6 checks still apply.
"""
import hashlib
import json
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from cross_section_scan import section_loops_detail
from outlet_selection_lineage import signed_distance


class SelectionConstraintError(ValueError):
    def __init__(self, message, details):
        super().__init__(message)
        self.details = details


def _mesh(points, faces):
    points, faces = np.asarray(points, float), np.asarray(faces)
    if (points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all()
            or faces.ndim != 2 or faces.shape[1] != 3 or faces.dtype.kind not in 'iu'
            or not len(faces) or faces.min() < 0 or faces.max() >= len(points)):
        raise ValueError('Expected finite source points and integer triangle indices')
    return points, faces.astype(np.int64, copy=False)


def selection_binding(points, faces, spec):
    points, faces = _mesh(points, faces)
    digest = hashlib.sha256()
    for value in (np.asarray(points, dtype='<f8'), np.asarray(faces, dtype='<i8')):
        digest.update(str(value.shape).encode('ascii'))
        digest.update(value.tobytes())
    plane = {key: spec[key] for key in ('point_lps_mm', 'normal_lps', 'keep_positive', 'roi_lps_mm')}
    return {'source_array_sha256': digest.hexdigest(),
            'plane_sha256': hashlib.sha256(json.dumps(plane, sort_keys=True, separators=(',', ':'),
                                                       allow_nan=False).encode('utf-8')).hexdigest()}


def _analysis(points, faces, spec, tolerance_mm):
    if not np.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise ValueError('Tolerance must be finite and positive')
    points, faces = _mesh(points, faces)
    signed = signed_distance(points, spec, tolerance_mm)
    if np.any(signed == 0):
        raise ValueError('Target-loop trial requires a plane without source vertices in its tolerance band')
    _, _, diag, detail = section_loops_detail(points, faces, spec['point_lps_mm'], spec['normal_lps'])
    if not detail['loops'] or diag['open_nodes'] or any(int(k) != 2 and v for k, v in diag['degree_histogram'].items()):
        raise ValueError('Target-loop trial requires closed degree-two section loops')
    for loop in detail['loops']:
        if any(int(b) not in detail['adjacency'][int(a)] for a,b in zip(loop, np.roll(loop,-1))):
            raise ValueError('Target-loop trial found an unclosed contour')
    negative = signed < 0
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    edges = edges[negative[edges].all(axis=1)]
    graph = coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])),
                       shape=(len(points), len(points))).tocsr()
    _, labels = connected_components(graph, directed=False)
    components = []
    for rim in detail['loop_faces']:
        vertices = np.unique(faces[rim])
        components.append(set(labels[vertices[negative[vertices]]].tolist()))
    return points, faces, negative, labels, components, detail, diag


def target_loop_catalog(points, faces, spec, *, tolerance_mm=1e-7):
    """List exact section alternatives; loop IDs carry no anatomy decision."""
    p, f, negative, labels, components, detail, diag = _analysis(points, faces, spec, tolerance_mm)
    return {'schema': 'outlet_target_loop_candidates/v1', 'binding': selection_binding(p, f, spec),
            'coordinate_system': 'LPS', 'unit': 'mm', 'section_diagnostics': diag,
            'anatomical_target_selected': False,
            'loops': [{'id': i, 'area_mm2': float(detail['loop_areas_mm2'][i]),
                       'rim_source_faces': detail['loop_faces'][i].tolist(),
                       'contour_lps_mm': detail['cut_points_3d'][loop].tolist(),
                       'negative_components': sorted(components[i]),
                       'coupled_loop_ids': [j for j,c in enumerate(components) if c & components[i]]}
                      for i,loop in enumerate(detail['loops'])]}


def constrained_target_selector(points, faces, spec, target_loop_ids, *, expected_binding,
                                protected_vertices=None, allowed_delete_vertices=None, tolerance_mm=1e-7):
    """Build a whole-component selector only from explicitly selected loop IDs.

    The caller owns the anatomical meaning of IDs/regions. This function rejects
    stale geometry/plane identity, unintended coupled loops, and any protection
    or allowed-region conflict. It never filters conflicting vertices out.
    """
    binding = selection_binding(points, faces, spec)
    if binding != expected_binding:
        raise ValueError('Target-loop binding does not match this exact source mesh and plane')
    p, f, negative, labels, components, detail, diag = _analysis(points, faces, spec, tolerance_mm)
    target = list(target_loop_ids)
    if not target or any(type(x) is not int or x < 0 or x >= len(components) for x in target) or len(set(target)) != len(target):
        raise ValueError('Target-loop IDs must be distinct existing integers')
    reached = set().union(*(components[i] for i in target))
    coupled = {i for i,c in enumerate(components) if c & reached}
    if coupled != set(target):
        raise SelectionConstraintError('Target region is inseparable from an unrequested section loop',
                                       {'target_loop_ids':target,'coupled_loop_ids':sorted(coupled)})
    selected = negative & np.isin(labels, list(reached))
    for key, raw, conflict_if in (('protected_vertices', protected_vertices, True),
                                  ('allowed_delete_vertices', allowed_delete_vertices, False)):
        if raw is None:
            continue
        mask = np.asarray(raw)
        if mask.ndim != 1 or len(mask) != len(p) or mask.dtype.kind != 'b':
            raise ValueError(key + ' must be a boolean per source vertex')
        conflict = selected & (mask if conflict_if else ~mask)
        if conflict.any():
            raise SelectionConstraintError('Target negative component conflicts with ' + key,
                                           {'constraint':key,'conflicting_source_vertex_ids':np.flatnonzero(conflict).tolist(),
                                            'target_loop_ids':target,'negative_components':sorted(reached)})
    return selected, {'binding':binding,'target_loop_ids':target,'negative_components':sorted(reached),
                      'selected_vertices':int(selected.sum()),'selection':'explicit_target_loops_whole_negative_components',
                      'final_clipper_area_N6_required':True,'anatomy_approved':False,'patient_solver_allowed':False}
