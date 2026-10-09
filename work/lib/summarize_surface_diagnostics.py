"""Bind isolated localization/origin evidence and summarize without coordinates."""
import argparse
from collections import Counter
from pathlib import Path

import numpy as np

from ct_case_pipeline import read_json, sha256, write_json
from locate_surface_intersections import load_triangles


def signature(triangle):
    return tuple(sorted(tuple(point) for point in triangle))


def bound_reports(root):
    summary = read_json(root / 'summary.json')
    records = {}
    for entry in summary['cases']:
        case = entry['case']
        path = root / (case + '.json')
        if sha256(path) != entry['report_sha256']:
            raise ValueError('Localization report changed')
        report = read_json(path)
        source = Path(report['case_dir'])
        for name, digest in report['input_hashes'].items():
            if sha256(source / name) != digest:
                raise ValueError('Localization input changed')
        if sha256(source / 'combined.vtp') != report['precision']['native_vtp_sha256']:
            raise ValueError('Native geometry output changed')
        records[case] = report
    return records


def build_summary(localization, translated, origin):
    original_reports, translated_reports = bound_reports(localization), bound_reports(translated)
    origin_summary = read_json(origin / 'summary.json')
    origin_records = {entry['case']: entry for entry in origin_summary['cases']}
    cases = []
    for case in ('p2', 'p3t1'):
        native = original_reports[case]
        source_dir = Path(original_reports[case + '_source']['case_dir'])
        triangles, _ = load_triangles(source_dir)
        source_triangles = {signature(t): i for i, t in enumerate(triangles.astype(np.float32).astype(float))}
        mapping = []
        for candidate in native['candidate_triangles']:
            source_id = source_triangles.get(signature(candidate['vertices_lps_m']))
            mapping.append({'triangle': candidate['triangle'], 'patch': candidate['patch'],
                            'source_triangle': source_id,
                            'status': 'unchanged_source_face' if source_id is not None else 'new_or_modified_face'})
        provenance = {'native_localization_sha256': sha256(localization / (case + '.json')),
                    'source_combined_sha256': original_reports[case + '_source']['input_hashes']['combined.stl'],
                    'coordinate_mode': 'native_stl_float32', 'candidates': mapping,
                    'note': 'Exact coordinate-set match; no clinical inference or intersecting-pair identity',
                    'patient_solver_allowed': False}
        provenance_path = localization / (case + '_candidate_provenance.json')
        if provenance_path.exists():
            if read_json(provenance_path) != provenance:
                raise ValueError('Existing provenance has different inputs or results')
        else:
            write_json(provenance_path, provenance)
        for name in (case + '_source', case):
            report, moved = original_reports[name], translated_reports[name]
            origin_path = origin / name / 'manifest.json'
            if sha256(origin_path) != origin_records[name]['report_sha256']:
                raise ValueError('Translation control report changed')
            origin_report = read_json(origin_path)
            source = Path(report['case_dir'])
            if any(sha256(source / filename) != digest for filename, digest in origin_report['source_hashes'].items()):
                raise ValueError('Translation baseline changed')
            xyz, patches = load_triangles(source)
            patch_quality = {}
            for patch in np.unique(patches):
                ids = np.flatnonzero(patches == patch)
                tri = xyz[ids]
                lengths = np.linalg.norm(tri - np.roll(tri, 1, axis=1), axis=2) * 1000
                areas = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) / 2 * 1e6
                quality = 4 * np.sqrt(3) * areas / np.sum(lengths**2, axis=1)
                shortest = int(np.argmin(lengths.min(axis=1)))
                poorest = int(np.argmin(quality))
                patch_quality[str(patch)] = {
                    'triangles': len(ids), 'minimum_edge_mm': float(lengths.min()),
                    'minimum_edge_triangle': int(ids[shortest]),
                    'minimum_quality_equilateral_1': float(quality.min()),
                    'minimum_quality_triangle': int(ids[poorest])}
            baseline = read_json(source / 'manifest.json')['surface_check']['interpretation']
            cases.append({'case': name, 'baseline_hits': report['hit_count'],
                          'translated_hits': moved['hit_count'],
                          'native_status': baseline['status'],
                          'unresolved_native_hits': report['unresolved_native_hits'],
                          'unperturbed_edge_matches': report['hits_with_unperturbed_native_style_match'],
                          'candidate_patch_counts': report['candidate_patch_counts'],
                          'components_retained': report['component_count'],
                          'native_coordinate_set_verified': report['precision']['native_vtp_vertex_set_match'],
                          'translation_roundtrip_error_m': origin_report['maximum_inverse_coordinate_error_m'],
                          'patch_quality_source_double': patch_quality,
                          'candidate_provenance': dict(Counter(m['status'] for m in mapping)) if name == case else None,
                          'localization_sha256': sha256(localization / (name + '.json')),
                          'translated_localization_sha256': sha256(translated / (name + '.json')),
                          'origin_report_sha256': sha256(origin_path)})
    return {'schema': 'surface_diagnostic_evidence/v1', 'cases': cases,
            'evidence_paths': {'localization': str(localization), 'translated_localization': str(translated), 'origin_control': str(origin)},
            'interpretation': 'Native failure retained; no confirmed intersecting triangle pair; origin sensitivity demonstrated',
            'volume_mesh_generated': False, 'geometry_repaired': False,
            'patient_solver_allowed': False, 'patient_cfd_results': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--localization', type=Path, required=True)
    parser.add_argument('--translated', type=Path, required=True)
    parser.add_argument('--origin', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Preserve prior evidence summaries')
    report = build_summary(args.localization, args.translated, args.origin)
    write_json(args.output, report)
    for case in report['cases']:
        print(case['case'], case['candidate_provenance'], case['patch_quality_source_double'], flush=True)


if __name__ == '__main__':
    main()
