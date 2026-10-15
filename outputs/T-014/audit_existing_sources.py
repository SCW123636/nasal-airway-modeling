"""Read-only T-014 audit; no patient mesh load, clipping, meshing or CFD."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'work/lib'))
from connectivity_opened_surface import flood_mask, signed_of
from auto_opening_pipeline import load_planes, search_base, build_placed, plane_basis


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def known_answers():
    # Two disconnected triangles. The first has one seed in a tiny ROI;
    # its other two vertices lie outside the ROI but share negative edges.
    # The second has no seed. These exact geometric coordinates supply truth.
    points = np.array([[0,0,-1],[3,0,-1],[0,3,-1],
                       [10,0,-1],[11,0,-1],[10,1,-1]], float)
    faces = np.array([[0,1,2],[3,4,5]], int)
    spec = {'point_lps_mm': [0,0,0], 'normal_lps': [0,0,1], 'keep_positive': True,
            'roi_lps_mm': {'min': [-.1,-.1,-1.1], 'max': [.1,.1,-.9]}}
    expected = [True, True, True, False, False, False]
    mask, note = flood_mask(points, faces, spec, seed_mode='roi')
    assert mask.tolist() == expected
    signed = signed_of(np.array([[0,0,-1],[0,0,1],[0,0,-.5e-7]]), spec)
    assert signed.tolist() == [-1., 1., 0.]
    inverted = dict(spec, keep_positive=False)
    assert signed_of(points, inverted).tolist() == [1.] * 6
    try:
        flood_mask(points, faces, inverted, seed_mode='roi')
    except ValueError as exc:
        flipped_error = str(exc)
        assert 'no negative-side seed' in flipped_error
    else:
        raise AssertionError('Flipped half-space unexpectedly found a seed')
    return {'source': 'literal coordinates in outputs/T-014/audit_existing_sources.py::known_answers',
            'scope': 'six vertices/two graph components; no patient geometry experiment',
            'expected_selection': expected, 'actual_selection': mask.tolist(), 'production_note': note,
            'signed_known_answer': signed.tolist(), 'flipped_keep_positive_error': flipped_error,
            'conclusion': 'ROI seeds, not a propagation boundary; positive/on-plane vertices are not deleted',
            'passed': True}


def audit():
    start = read(ROOT / 'outputs/T-013/start_fingerprints.json')
    landmark_path = ROOT / 'work/06_auto_landmarks/p0/landmarks.json'
    landmark = read(landmark_path)
    previous = read(ROOT / 'outputs/T-013/real_cases_results.json')['cases']['p0']
    scope = read(ROOT / 'outputs/T-013/mask_scope_results.json')
    production_report_path = Path('C:/ts_work/batch27_opening/p0.json')
    production = read(production_report_path)
    pipeline_record_path = ROOT / 'outputs/T-011/a0_p0_run.json'
    pipeline_record = read(pipeline_record_path)['rows']['p0']
    # Reconstruct only deterministic plane transforms; never invoke process/clip/flood on p0.
    planes, provenance, plane_sha, admitted = load_planes(ROOT / 'work/06_auto_landmarks', None,
                                                        'p0', allow_needs_review=True)
    assert production['plane_source'] == provenance == 'automatic_proposal'
    assert production['plane_source_sha256'] == plane_sha == digest(landmark_path)
    assert pipeline_record['s3_propose']['landmarks_sha256'] == plane_sha
    assert production['search_origin'] == production['requested_search_origin'] == 'reviewed'
    assert 'origin_downgrade' not in production
    assert production['search_start_mm'] == 0
    assert not any(production['placement_evidence']['entered_bisection'].values())
    assert all(v == 0 for v in production['offset_from_reviewed_mm'].values())
    base = search_base(production['onset_offset_mm'], production['search_origin'])
    final_planes = build_placed(planes, {key: plane_basis(spec['normal_lps'])[0]
                                        for key, spec in planes.items()}, base,
                                {key: 0.0 for key in planes})
    assert final_planes == previous['planes']
    identity = []
    for entry in start['dependencies'] + start['landmarks']:
        path = Path(entry['path'])
        if path.name not in ('partitioned_surface.py', 'connectivity_opened_surface.py',
                             'auto_opening_pipeline.py', 'source_surface.vtp', 'landmarks.json'):
            continue
        actual = digest(path)
        identity.append({'path': str(path), 'expected_T013_sha256': entry['sha256'].lower(),
                         'current_sha256': actual, 'same_as_T013': actual == entry['sha256'].lower()})
    assert all(entry['same_as_T013'] for entry in identity)
    # Use only the already stored 774-conflict subset, never re-run patient clipping/flood.
    collision_path = ROOT / 'outputs/T-013/collision_nasopharynx_outlet.npz'
    with np.load(collision_path, allow_pickle=False) as collision:
        tri = collision['triangles'];stored_signed = collision['signed']
        spec = json.loads(str(collision['spec_json'].item()))
        normal = np.asarray(spec['normal_lps'], float);normal /= np.linalg.norm(normal)
        normal = normal if spec['keep_positive'] else -normal
        distances = (tri - spec['point_lps_mm']) @ normal
        assert np.allclose(distances, stored_signed, rtol=0, atol=1e-10)
        patch, count = np.unique(collision['patch'], return_counts=True)
        lo, hi = np.asarray(spec['roi_lps_mm']['min']), np.asarray(spec['roi_lps_mm']['max'])
        all_inside_roi = ((tri >= lo) & (tri <= hi)).all(axis=(1,2))
        fully_negative = (distances < 0).all(axis=1)
        strict_straddling = (distances.min(axis=1) < 0) & (distances.max(axis=1) > 0)
        cap_summary = {'source': str(collision_path.relative_to(ROOT)), 'source_sha256': digest(collision_path),
                       'triangles': len(tri), 'patch_counts': dict(zip(patch.tolist(), count.tolist())),
                       'fully_negative_triangles': int(fully_negative.sum()),
                       'strict_straddling_triangles': int(strict_straddling.sum()),
                       'triangles_all_vertices_inside_outlet_roi': int(all_inside_roi.sum()),
                       'distance_min_mm': float(distances.min()), 'distance_max_mm': float(distances.max()),
                       'stored_distance_matches_source_definition': True,
                       'bounds_lps_mm': {'min': tri.min(axis=(0,1)).tolist(), 'max': tri.max(axis=(0,1)).tolist()}}
    assert cap_summary['triangles'] == previous['control']['details']['conflicting_triangles']
    outlet = landmark['landmarks']['nasopharynx_outlet']
    input_audit = {'recorded_at': datetime.now().astimezone().isoformat(),
                   'script_sha256': digest(__file__), 'identity': identity,
                   'landmark_header': {k: landmark.get(k) for k in ('schema','case','coordinate_system','unit','status','source_ct','input_provenance')},
                   'outlet': {k: outlet.get(k) for k in ('status','point_lps_mm','normal_lps','roi_lps_mm','clinical_validation','acceptance_meaning','consistency_checks','review_reasons')},
                   'outlet_evidence': {k: v for k,v in outlet['evidence'].items() if k != 'threshold_variants'},
                   'production_plane_matches_frozen_landmark': previous['planes']['nasopharynx_outlet'] == {
                       **{k: outlet[k] for k in ('point_lps_mm','normal_lps','roi_lps_mm')}, 'keep_positive': True},
                   'T011_actual_input_chain': {
                       'production_report': str(production_report_path), 'production_report_sha256': digest(production_report_path),
                       'pipeline_run_record': str(pipeline_record_path.relative_to(ROOT)),
                       'pipeline_run_record_sha256': digest(pipeline_record_path),
                       'plane_source': production['plane_source'], 'plane_source_sha256': production['plane_source_sha256'],
                       'clinical_status': production['clinical_status'],
                       'search_origin': production['search_origin'], 'requested_search_origin': production['requested_search_origin'],
                       'search_start_mm': production['search_start_mm'], 'search_base_mm': base,
                       'offset_from_reviewed_mm': production['offset_from_reviewed_mm'],
                       'offset_from_onset_mm': production['offset_from_onset_mm'],
                       'entered_bisection': production['placement_evidence']['entered_bisection'],
                       'origin_downgrade_present': 'origin_downgrade' in production,
                       'final_planes_reconstructed_by_production_pure_functions': final_planes,
                       'matches_T013_actual_control_spec': final_planes == previous['planes'],
                       'seed_notes': production['selection_notes'], 'admitted_needs_review': admitted,
                       'original_placed_arguments_separately_persisted': False,
                       'reconstruction_basis': 'recorded reviewed origin/start0/no bisection; pure search_base/build_placed preserve point, normal, ROI, keep side',
                       'reviewed_is_human_review': False},
                   'original_selection_trace': previous['control']['selector_trace'],
                   'mask_lifetime_trace': scope['trace'], 'collision_subset': cap_summary,
                   'outlet_alone_area_vs_engineering_band': previous['outlet_alone_area_vs_engineering_band'],
                   'original_known_answers': {'source':'outputs/T-013/synthetic_results.json',
                       'sha256': digest(ROOT/'outputs/T-013/synthetic_results.json'),
                       'source_script': 'outputs/T-013/production_probe.py',
                       'scope':'reuse previous actual production clip control; not rerun'},
                   'known_answers': known_answers(),
                   'patient_mesh_loaded': False, 'patient_flood_or_clipper_rerun': False,
                   'production_modified': False, 'anatomy_approved': False}
    write('source_audit.json', input_audit)
    print(json.dumps({'identity_unchanged': all(x['same_as_T013'] for x in identity),
                      'production_plane_matches': input_audit['production_plane_matches_frozen_landmark'],
                      'cap_subset': cap_summary, 'known_answers_passed': True,
                      'patient_geometry_rerun': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    audit()
