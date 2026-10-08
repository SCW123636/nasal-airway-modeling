"""Synthetic reconstruction experiments; never read patient case directories.

Optionally compare the actual Windcatcher source at a pinned commit. No source
from that repository is copied into this project or modified by this runner.
"""
import argparse
from collections import Counter
import hashlib
import importlib
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
import SimpleITK as sitk
import vtk

from ct_case_pipeline import sha256, write_json
from export_candidate_preview import mask_surface, surface_stats, triangle_arrays
from mask_revision_store import MaskRevisionStore
from planar_cap import triangulate_cap


REFERENCE_COMMIT = 'e12d77136040dded6449a921ecac186f1f9c4970'


def square(low, high):
    return np.array([[low, low, 0], [high, low, 0], [high, high, 0],
                     [low, high, 0]], dtype=float)


def face_metrics(vertices, faces, normal=None):
    faces = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    cross = np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]],
                     vertices[faces[:, 2]] - vertices[faces[:, 0]])
    directed = [(int(a), int(b)) for face in faces
                for a, b in zip(face, np.roll(face, -1))]
    counts = Counter(tuple(sorted(edge)) for edge in directed)
    balance = Counter()
    for a, b in directed:
        balance[tuple(sorted((a, b)))] += 1 if a < b else -1
    return {'area_mm2': float(np.linalg.norm(cross, axis=1).sum() * .5),
            'triangles': len(faces),
            'boundary_edges': sum(n == 1 for n in counts.values()),
            'nonmanifold_edges': sum(n > 2 for n in counts.values()),
            'inconsistent_winding_edges': sum(n == 2 and balance[e] != 0
                                               for e, n in counts.items()),
            'degenerate_triangles': int(np.count_nonzero(np.linalg.norm(cross, axis=1) < 1e-12)),
            'normal_reversed_triangles': (int(np.count_nonzero(cross @ normal <= 0))
                                          if normal is not None else None)}


def wind_faces(vertices, loops, normal, reference):
    faces = []
    for loop in loops:
        local = reference(vertices[np.asarray(loop)], np.asarray(normal, dtype=float))
        faces.extend(np.asarray(loop, dtype=np.int64)[local].tolist())
    return np.asarray(faces, dtype=np.int64).reshape(-1, 3)


def cap_experiments(reference=None):
    cases = [
        ('concave_u', np.array([[0, 0, 0], [4, 0, 0], [4, 4, 0], [3, 4, 0],
                               [3, 1, 0], [1, 1, 0], [1, 4, 0], [0, 4, 0]], float),
         [list(range(8))], 10),
        ('hole', np.vstack((square(0, 4), square(1, 3))),
         [list(range(4)), list(range(4, 8))], 12),
        ('nested_island', np.vstack((square(0, 4), square(1, 3), square(1.5, 2.5))),
         [list(range(start, start + 4)) for start in (0, 4, 8)], 13),
    ]
    results = []
    for name, vertices, loops, expected in cases:
        faces, qc = triangulate_cap(vertices, loops, [0, 0, 1])
        assert abs(qc['area_mm2'] - expected) < 1e-9
        item = {'case': name, 'analytic_area_mm2': expected,
                'new': face_metrics(vertices, faces, [0, 0, 1]), 'qc': qc}
        if reference:
            old = wind_faces(vertices, loops, [0., 0., 1.], reference)
            item['windcatcher'] = face_metrics(vertices, old, [0, 0, 1])
        results.append(item)
    crossing = np.array([[0, 0, 0], [4, 4, 0], [0, 4, 0], [4, 0, 0]], float)
    try:
        triangulate_cap(crossing, [list(range(4))], [0, 0, 1])
    except ValueError as exc:
        item = {'case': 'self_crossing', 'new_rejected': str(exc)}
    else:
        raise AssertionError('Self-crossing contour was accepted')
    if reference:
        item['windcatcher'] = face_metrics(crossing,
                                           reference(crossing, np.array([0., 0., 1.])))
    results.append(item)
    return results


def closed_hollow_prism(reference=None):
    bottom = np.vstack((square(0, 4), square(1, 3)))
    vertices = np.vstack((bottom, bottom + [0, 0, 5]))
    # Outer CCW and inner CW walls have outward normals for a hollow prism.
    wall = []
    for loop in ([0, 1, 2, 3], [7, 6, 5, 4]):
        for a, b in zip(loop, loop[1:] + loop[:1]):
            wall.extend(([a, b, b + 8], [a, b + 8, a + 8]))
    all_faces = list(wall)
    for shift, normal in ((0, [0, 0, -1]), (8, [0, 0, 1])):
        loops = [list(range(start + shift, start + shift + 4)) for start in (0, 4)]
        faces, _ = triangulate_cap(vertices, loops, normal)
        all_faces.extend(faces.tolist())
    new = face_metrics(vertices, all_faces)
    assert all(new[key] == 0 for key in ('boundary_edges', 'nonmanifold_edges',
                                         'inconsistent_winding_edges', 'degenerate_triangles'))
    item = {'case': 'hollow_prism_wall_plus_caps', 'new': new,
            'scope': 'synthetic surface topology; no volume mesh or solver'}
    if reference:
        old = list(wall)
        for shift, normal in ((0, [0., 0., -1.]), (8, [0., 0., 1.])):
            loops = [list(range(start + shift, start + shift + 4)) for start in (0, 4)]
            old.extend(wind_faces(vertices, loops, normal, reference).tolist())
        item['windcatcher'] = face_metrics(vertices, old)
    return item


def mask_roundtrip():
    mask = np.zeros((8, 10, 12), np.uint8)
    mask[2:6, 2:8, 2:10] = 1
    geometry = {'coordinate_system': 'LPS', 'unit': 'mm', 'shape_zyx': list(mask.shape),
                'spacing_mm': [1.4, 1.2, .8], 'origin_lps_mm': [20, -30, 40],
                'axis_dirs': [[0, 0, 1], [0, 1, 0], [1, 0, 0]]}
    ct_hash = hashlib.sha256(np.full(mask.shape, -1000, np.int16).tobytes()).hexdigest()

    def surface(values):
        image = sitk.GetImageFromArray(values)
        image.SetSpacing(geometry['spacing_mm'][::-1])
        image.SetOrigin(geometry['origin_lps_mm'])
        image.SetDirection(np.asarray(geometry['axis_dirs'])[::-1].T.ravel().tolist())
        poly, _ = mask_surface(image)
        points, faces = triangle_arrays(poly)
        return points, faces, surface_stats(poly)

    with tempfile.TemporaryDirectory(prefix='synthetic_mask_history_') as directory:
        store = MaskRevisionStore(directory)
        initial = store.commit(mask, mask, ct_sha256=ct_hash, geometry=geometry,
                               expected_revision=None, action='initial', reviewer='Synthetic QA')
        original = surface(store.load()[2]['main'])
        edited_mask = mask.copy()
        edited_mask[2:6, 2:8, 10] = 1
        edited = store.commit(edited_mask, edited_mask, ct_sha256=ct_hash, geometry=geometry,
                              expected_revision=initial, reviewer='Synthetic QA')
        changed = surface(store.load()[2]['main'])
        assert changed[2]['enclosed_volume_mm3'] > original[2]['enclosed_volume_mm3']
        restored = store.restore(initial, expected_revision=edited, reviewer='Synthetic QA')
        revision, record, masks = store.load()
        recovered = surface(masks['main'])
        assert revision == restored and restored != initial
        assert np.array_equal(original[0], recovered[0]) and np.array_equal(original[1], recovered[1])
        assert not record['patient_solver_allowed'] and set(record['downstream_status'].values()) == {'stale'}
        return {'case': 'mask_edit_undo_surface_rebuild', 'sequence': record['sequence'],
                'surface_exactly_restored': True, 'review_status': record['review_status'],
                'downstream_status': record['downstream_status'], 'patient_solver_allowed': False,
                'original_surface': original[2], 'edited_surface': changed[2],
                'restored_surface': recovered[2]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windcatcher-root', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    reference, identity = None, None
    if args.windcatcher_root:
        root = args.windcatcher_root.resolve()
        commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
        if commit != REFERENCE_COMMIT:
            raise ValueError('Reference commit differs from the reviewed version')
        source = root / 'pipeline' / 'surface.py'
        if subprocess.run(['git', '-C', str(root), 'diff', '--quiet', 'HEAD', '--',
                           'pipeline/surface.py']).returncode != 0:
            raise ValueError('Reference source has local changes')
        sys.path.insert(0, str(root))
        reference = importlib.import_module('pipeline.surface')._triangulate_plane_loop
        identity = {'repository': 'https://github.com/Handsome5201314/windcatcher',
                    'commit': commit, 'surface_source_sha256': sha256(source), 'license': 'MIT'}
    report = {'schema': 'reconstruction_component_validation/v1',
              'scope': 'synthetic engineering experiments only', 'patient_cfd_results': 0,
              'patient_solver_allowed': False, 'reference': identity,
              'versions': {'numpy': np.__version__, 'vtk': vtk.vtkVersion.GetVTKVersion(),
                           'simpleitk': sitk.Version_VersionString()},
              'caps': cap_experiments(reference), 'closed_surface': closed_hollow_prism(reference),
              'mask_history': mask_roundtrip(),
              'source_sha256': {name: sha256(Path(__file__).parent / name) for name in
                                ('planar_cap.py', 'mask_revision_store.py', Path(__file__).name)}}
    write_json(args.out, report)
    print('Synthetic reconstruction components passed: ' + str(args.out.resolve()))


if __name__ == '__main__':
    main()
