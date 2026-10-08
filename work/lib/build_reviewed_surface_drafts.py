"""Build exact surface drafts from adopted points, with no medical gate promotion.

All geometry remains in a new private output directory. Point review does not
approve oral/sinus scope, generated caps, volume meshes or patient CFD.
"""
import argparse
from pathlib import Path
import re

import numpy as np
import vtk

from adopt_landmark_feedback import MedicalReviewStore, latest_current_feedback
from build_auto_landmark_review import sha256_json
from ct_case_pipeline import CaseManager, read_json, sha256, write_json
from export_candidate_preview import (mask_surface, read_image_local, set_triangle_arrays,
                                      triangle_arrays, validate_source_geometry, write_vtp)
from partitioned_surface import clip_and_cap, topology
from boundary_preview import VIEWS, montage, render_panel, slice_grid


def load_adopted(store, case):
    storage = store.storage(case)
    pointer = read_json(storage / 'landmarks_current.json')
    revision = pointer['revision']
    if not re.fullmatch(r'l_[0-9a-f]{64}', revision):
        raise ValueError('Invalid adopted revision')
    directory = storage / 'adopted_landmarks' / revision
    manifest = read_json(directory / 'manifest.json')
    if sha256(directory / 'manifest.json') != pointer['manifest_sha256']:
        raise ValueError('Adopted manifest content changed')
    if set(manifest['artifacts']) != {'decisions.json', 'review_config_confirmed.json'}:
        raise ValueError('Incomplete adopted artifact manifest')
    for name, expected in manifest['artifacts'].items():
        if name not in ('decisions.json', 'review_config_confirmed.json') or sha256(directory / name) != expected:
            raise ValueError('Adopted artifact changed')
    config = read_json(directory / 'review_config_confirmed.json')
    if 'l_' + sha256_json(config) != revision:
        raise ValueError('Adopted config changed')
    _, _, _, identity = store.point_source(case)
    if identity != manifest['identity']:
        raise ValueError('Point review is stale')
    binding = config['feedback_binding']
    if latest_current_feedback(store, case)['id'] != binding['id']:
        raise ValueError('A newer human feedback record supersedes adopted decisions')
    if sha256(storage / 'feedback' / (binding['id'] + '.json')) != binding['sha256']:
        raise ValueError('Adopted feedback changed')
    return config, directory / 'review_config_confirmed.json'


def write_surface(output, points, faces, labels=None):
    poly = vtk.vtkPolyData()
    set_triangle_arrays(poly, points, faces)
    if labels is not None:
        if len(labels) != len(faces):
            raise ValueError('One boundary label is required per triangle')
        values = vtk.vtkStringArray()
        values.SetName('boundary_patch')
        for name in labels:
            values.InsertNextValue(str(name))
        poly.GetCellData().AddArray(values)
    write_vtp(poly, output)
    if labels is not None:
        reader = vtk.vtkXMLPolyDataReader()
        reader.SetFileName(str(output))
        reader.Update()
        restored = reader.GetOutput().GetCellData().GetAbstractArray('boundary_patch')
        if (restored is None or restored.GetNumberOfValues() != len(labels)
                or any(restored.GetValue(i) != str(name) for i, name in enumerate(labels))):
            raise ValueError('Saved surface boundary labels changed')


def candidate_inputs(case, anatomy_root, config, review_path):
    manifest_path = anatomy_root / case / 'anatomy' / 'manifest.json'
    source = read_json(manifest_path)
    mask_path = Path(source['threshold_candidates']['-300']['path']).resolve()
    ct_path = Path(source['source_ct']).resolve()
    if (source['case'] != case or source['coordinate_system'] != 'LPS' or source['unit'] != 'mm'
            or not mask_path.is_relative_to(manifest_path.parent.resolve())
            or sha256(ct_path) != config['feedback_binding']['identity']['input_sha256']['ct.nii.gz']):
        raise ValueError('Candidate source identity mismatch')
    inputs = {name: sha256(path) for name, path in
              (('mask', mask_path), ('ct', ct_path), ('manifest', manifest_path), ('point_review', review_path))}
    return source, mask_path, ct_path, inputs


def build_case(store, case, anatomy_root, output):
    output.mkdir(parents=True, exist_ok=False)
    config, review_path = load_adopted(store, case)
    source, mask_path, ct_path, inputs = candidate_inputs(case, anatomy_root, config, review_path)
    image = read_image_local(mask_path)
    validate_source_geometry(image, source)
    poly, mask_info = mask_surface(image)
    if mask_info['voxels'] != source['threshold_candidates']['-300']['voxels']:
        raise ValueError('Candidate voxel count changed')
    points, faces = triangle_arrays(poly)
    write_surface(output / 'source_surface.vtp', points, faces)
    initial, _ = topology(points, faces)
    planes = {name: config['planes_lps'][name] for name in
              ('nostril_L', 'nostril_R', 'nasopharynx_outlet')}
    if any(spec['status'] != 'confirmed' for spec in planes.values()):
        raise ValueError('All three point planes must be confirmed')
    report = {'schema': 'reviewed_points_surface_draft/v1', 'case': case, 'inputs': inputs,
              'scope': 'engineering draft from current point review', 'coordinate_system': 'LPS', 'unit': 'mm',
              'source_topology': initial, 'point_review_revision': review_path.parent.name,
              'oral_exclusion_review': 'pending', 'sinus_policy_review': 'pending',
              'final_geometry_review': 'pending', 'patient_solver_allowed': False,
              'patient_cfd_results': 0, 'individual_planes': {}}
    ct = None
    for name, spec in planes.items():
        try:
            new_points, new_faces, labels, qc = clip_and_cap(points, faces, {name: spec})
            write_surface(output / (name + '_draft.vtp'), new_points, new_faces, labels)
            report['individual_planes'][name] = {'status': 'technical_pass', 'report': qc}
        except ValueError as exc:
            report['individual_planes'][name] = {'status': 'technical_fail', 'reason': str(exc)}
            details = getattr(exc, 'details', None)
            if details:
                report['individual_planes'][name]['details'] = details
                if ct is None:
                    ct = read_image_local(ct_path)
                centers = np.asarray(details['triangle_centers_lps_mm'])
                focus = centers[np.argmin(np.linalg.norm(centers - centers.mean(axis=0), axis=1))]
                panels = []
                for view, axes in VIEWS.items():
                    grid = slice_grid(focus, *axes, pixels=513, field_mm=40)
                    panel, _ = render_panel(ct, image, None, grid, {name: spec},
                                            name + ' ROI conflict / ' + view)
                    panels.append(panel)
                montage(panels, output / (name + '_roi_conflict.png'),
                        'ENGINEERING FAILURE - point approval valid; boundary scope unresolved')
    try:
        new_points, new_faces, labels, qc = clip_and_cap(points, faces, planes)
        write_surface(output / 'partitioned_draft.vtp', new_points, new_faces, labels)
        report['combined'] = {'status': 'technical_pass', 'report': qc}
    except ValueError as exc:
        report['combined'] = {'status': 'technical_fail', 'reason': str(exc)}
    if inputs != candidate_inputs(case, anatomy_root, config, review_path)[3]:
        raise ValueError('Source changed during surface generation')
    load_adopted(store, case)
    report['source_unchanged'] = True
    report['artifacts'] = {p.name: sha256(p) for p in output.iterdir() if p.suffix in ('.vtp', '.png')}
    write_json(output / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-root', type=Path, default=Path('C:/ts_work/project_cases'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', default=['p0', 'p1', 'p2', 'p3', 'p3t1'])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    work = Path(__file__).resolve().parents[1]
    manager = CaseManager(args.case_root)
    summary = []
    try:
        store = MedicalReviewStore(manager, work / '06_auto_landmarks')
        for case in args.cases:
            if case not in ('p0', 'p1', 'p2', 'p3', 'p3t1'):
                raise ValueError('Unknown case')
            report = build_case(store, case, work / '05_ts_seg', args.output / case)
            summary.append({'case': case, 'combined': report['combined'],
                            'individual_planes': report['individual_planes'], 'inputs': report['inputs'],
                            'source_topology': report['source_topology'], 'patient_solver_allowed': False})
            print(case + ': ' + report['combined']['status'] + ' ' + report['combined'].get('reason', ''), flush=True)
        write_json(args.output / 'summary.json', {'cases': summary, 'patient_cfd_results': 0})
    finally:
        manager.pool.shutdown(wait=True)


if __name__ == '__main__':
    main()
