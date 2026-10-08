"""Adopt current imported human point feedback; never approve final geometry.

Versioned results live in the private review store. Original proposals, masks,
feedback and prior adopted generations remain unchanged.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

from build_auto_landmark_review import sha256_json
from confirm_landmark_review import build_confirmed, validate
from ct_case_pipeline import CaseManager, execution_lock, read_json, sha256, write_json
from medical_review import EXISTING_CASES, MedicalReviewStore


def latest_current_feedback(service, case):
    records = [r for r in service.list_feedback(case)['records']
               if r['current'] and r['feedback']['stage'] == 'landmarks']
    if not records:
        raise ValueError('No current imported landmark feedback')
    latest = records[0]
    if any(r['imported_at'] == latest['imported_at'] for r in records[1:]):
        raise ValueError('Ambiguous latest feedback; explicitly resolve the human decisions')
    items = latest['feedback']['items']
    if not items or any(item['decision'] not in ('accept', 'adjust') for item in items):
        raise ValueError('Every point must be accepted or explicitly adjusted')
    return latest


def adopt(service, case):
    if case not in EXISTING_CASES:
        raise ValueError('This adapter is restricted to existing reviewed scans')
    storage = service.storage(case)
    storage.mkdir(parents=True, exist_ok=True)
    with execution_lock(storage):
        feedback = latest_current_feedback(service, case)
        source_path = storage / 'feedback' / (feedback['id'] + '.json')
        source_hash = sha256(source_path)
        if feedback['id'] != 'f_' + sha256_json(feedback['feedback'])[:24]:
            raise ValueError('Feedback content hash changed')
        items = feedback['feedback']['items']
        decisions = service.decisions(case, feedback['id'], [item['id'] for item in items])
        _, _, bundle, identity = service.point_source(case)
        checked, problems, reviewer = validate(decisions, bundle)
        if problems or len(checked) != 1 or checked[0]['undecided']:
            raise ValueError('Incomplete or mismatched point decisions: ' + '; '.join(problems))
        config = build_confirmed(checked, reviewer, None, None, False, False,
                                 feedback['feedback']['reviewed_at'])[case]
        config['generated_at'] = feedback['imported_at']
        config['feedback_binding'] = {'id': feedback['id'], 'sha256': source_hash,
                                      'package_sha256': feedback['feedback']['package_sha256'],
                                      'identity': identity}
        revision = 'l_' + sha256_json(config)
        parent = storage / 'adopted_landmarks'
        parent.mkdir(exist_ok=True)
        destination = parent / revision
        if destination.exists():
            summary = read_json(destination / 'manifest.json')
            if set(summary['artifacts']) != {'decisions.json', 'review_config_confirmed.json'}:
                raise ValueError('Incomplete adopted artifact manifest')
            for name, expected in summary['artifacts'].items():
                if name not in ('decisions.json', 'review_config_confirmed.json') or sha256(destination / name) != expected:
                    raise ValueError('Existing adopted artifact changed')
            if read_json(destination / 'review_config_confirmed.json') != config:
                raise ValueError('Existing adopted config changed')
            if (service.point_source(case)[3] != identity or sha256(source_path) != source_hash
                    or latest_current_feedback(service, case)['id'] != feedback['id']):
                raise ValueError('Inputs or feedback changed during adoption')
            write_json(storage / 'landmarks_current.json',
                       {'revision': revision, 'manifest_sha256': sha256(destination / 'manifest.json')})
            return summary | {'directory': str(destination)}
        stage = Path(tempfile.mkdtemp(prefix='.pending-', dir=parent))
        try:
            write_json(stage / 'decisions.json', decisions)
            write_json(stage / 'review_config_confirmed.json', config)
            summary = {'schema': 'adopted_landmark_feedback/v1', 'case': case,
                       'revision': revision, 'feedback_id': feedback['id'],
                       'identity': identity, 'confirmed_points': [i['id'] for i in items],
                       'confirmed_cutting_planes': config['confirmed_boundaries'],
                       'scope': 'point localization only',
                       'oral_exclusion_confirmed': False, 'sinus_policy_confirmed': False,
                       'final_geometry_approved': False, 'patient_solver_allowed': False,
                       'artifacts': {name: sha256(stage / name) for name in
                                     ('decisions.json', 'review_config_confirmed.json')}}
            write_json(stage / 'manifest.json', summary)
            if (service.point_source(case)[3] != identity or sha256(source_path) != source_hash
                    or latest_current_feedback(service, case)['id'] != feedback['id']):
                raise ValueError('Inputs or feedback changed during adoption')
            if destination.exists():
                raise FileExistsError('Use the existing adopted generation: ' + str(destination))
            os.replace(stage, destination)
            write_json(storage / 'landmarks_current.json',
                       {'revision': revision, 'manifest_sha256': sha256(destination / 'manifest.json')})
            return summary | {'directory': str(destination)}
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-root', type=Path, default=Path('C:/ts_work/project_cases'))
    parser.add_argument('--review-root', type=Path, default=Path(__file__).resolve().parents[1] / '06_auto_landmarks')
    parser.add_argument('--cases', nargs='+', choices=EXISTING_CASES, default=list(EXISTING_CASES))
    args = parser.parse_args()
    manager = CaseManager(args.case_root)
    try:
        service = MedicalReviewStore(manager, args.review_root)
        for case in args.cases:
            print(json.dumps(adopt(service, case), ensure_ascii=False))
    finally:
        manager.pool.shutdown(wait=True)


if __name__ == '__main__':
    main()
