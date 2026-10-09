"""Isolated rigid-translation control for native surfaceCheck diagnostics.

Moves every point by the same saved vector, keeps every triangle and patch,
and checks reversible coordinates and translation-invariant topology. This
is a numerical control, never a patient repair or geometry acceptance.
"""
import argparse
from pathlib import Path

import numpy as np

from ct_case_pipeline import read_json, sha256, write_json
from locate_surface_intersections import load_triangles, PATCHES
from partitioned_surface import topology
from prepare_surface_preflight import native_check
from surface_to_case import parse_stl_ascii, write_patch_stl


def translation_control(source, output):
    manifest = read_json(source / 'manifest.json')
    paths = [source / 'manifest.json', source / 'combined.stl']
    paths += [source / (patch + '.stl') for patch in manifest['patches']]
    hashes = {p.name: sha256(p) for p in paths}
    if hashes['combined.stl'] != manifest['combined_sha256']:
        raise ValueError('Combined surface identity mismatch')
    for patch, record in manifest['patches'].items():
        if hashes[patch + '.stl'] != record['sha256']:
            raise ValueError('Patch surface identity mismatch')
    if output.exists():
        raise FileExistsError('Preserve earlier controls')
    triangles, labels = load_triangles(source)
    translation = (triangles.min(axis=(0, 1)) + triangles.max(axis=(0, 1))) / 2
    vertices, inverse = np.unique(triangles.reshape(-1, 3), axis=0, return_inverse=True)
    faces = inverse.reshape(-1, 3)
    original_qc, _ = topology(vertices * 1000, faces)
    moved_qc, _ = topology((vertices - translation) * 1000, faces)
    for key in ('boundary_edges', 'nonmanifold_edges', 'inconsistent_winding_edges',
                'duplicate_triangles', 'degenerate_triangles', 'triangles', 'vertices'):
        if original_qc[key] != moved_qc[key]:
            raise ValueError('Topology changed under rigid translation')
    for key in ('surface_area_mm2', 'signed_volume_mm3'):
        np.testing.assert_allclose(original_qc[key], moved_qc[key], rtol=1e-11, atol=1e-9)
    output.mkdir(parents=True)
    patches, pieces, max_error = {}, [], 0.
    for patch in PATCHES:
        if patch not in manifest['patches']:
            continue
        selected = triangles[labels == patch]
        path = output / (patch + '.stl')
        write_patch_stl(path, patch, ((selected - translation) * 1000).tolist())
        restored = np.asarray(parse_stl_ascii(path)[patch])
        error = float(np.max(np.abs(restored + translation - selected)))
        if error > 1e-14:
            raise ValueError('Roundtrip coordinate drift')
        max_error = max(max_error, error)
        patches[patch] = {'triangles': len(selected), 'sha256': sha256(path)}
        pieces.append(path.read_text(encoding='ascii'))
    (output / 'combined.stl').write_text(''.join(pieces), encoding='ascii')
    report = {'schema': 'native_surface_origin_control/v1',
              'source_hashes': hashes, 'generator_sha256': sha256(Path(__file__)),
              'translation_lps_m': translation.tolist(),
              'coordinate_system': 'translated LPS; original_lps_m = local_m + translation_lps_m',
              'output_unit': 'm', 'patches': patches,
              'combined_sha256': sha256(output / 'combined.stl'),
              'original_qc': original_qc, 'translated_qc': moved_qc,
              'maximum_inverse_coordinate_error_m': max_error,
              'baseline_native_check': manifest['surface_check']['interpretation'],
              'all_components_retained': True, 'geometry_repaired': False,
              'patient_solver_allowed': False, 'patient_cfd_results': 0, 'volume_mesh_generated': False}
    native_check(output, report)
    if any(sha256(p) != hashes[p.name] for p in paths):
        raise ValueError('Original inputs changed during control')
    write_json(output / 'manifest.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Use a new output directory')
    args.output.mkdir(parents=True)
    reports = []
    for case in ('p2_source', 'p2', 'p3t1_source', 'p3t1'):
        report = translation_control(args.preflight / case, args.output / case)
        reports.append({'case': case, 'baseline_hits': report['baseline_native_check']['edge_triangle_intersection_hits'],
                        'translated_native_check': report['surface_check']['interpretation'],
                        'maximum_inverse_coordinate_error_m': report['maximum_inverse_coordinate_error_m'],
                        'report_sha256': sha256(args.output / case / 'manifest.json')})
    write_json(args.output / 'summary.json', {'cases': reports, 'patient_solver_allowed': False,
                                             'patient_cfd_results': 0, 'geometry_repaired': False})


if __name__ == '__main__':
    main()
