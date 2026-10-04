"""Register human-accepted existing proposals as coarse-only references.

This is deliberately separate from ``confirm_landmark_review.py``: the
records initialize a search and never unlock geometry or CFD. Input hashes are
checked against the current CT and labels before anything is written.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from coarse_anatomy_prior import (DEFAULT_LIBRARY, SCHEMA, add_reference,
                                  load_descriptor, patient_id, read_json, sha256,
                                  validate_descriptor, validate_library, write_json)


def register_case(case, data_base, proposal_base, acceptance_sha256,
                  reviewer, reviewed_at):
    data_dir = Path(data_base) / case
    proposal_path = Path(proposal_base) / case / 'landmarks.json'
    proposal = read_json(proposal_path)
    if proposal.get('case') != case or proposal.get('coordinate_system') != 'LPS' or proposal.get('unit') != 'mm':
        raise ValueError(f'{case}: proposal identity/coordinates are not LPS/mm')
    descriptor, _ = load_descriptor(data_dir)
    quality_warning = None
    try:
        validate_descriptor(descriptor)
    except ValueError as exc:
        # A human-accepted coarse reference may be usable for initialization
        # while still being unsuitable for a target's own frame gate.
        quality_warning = str(exc)
        basic = dict(descriptor)
        basic['eligible'] = True
        basic['reasons'] = []
        validate_descriptor(basic, allow_frame_warning=True)
    current = {'ct.nii.gz': sha256(data_dir / 'ct.nii.gz')}
    from auto_anatomy_landmarks import NAMES
    current.update({f'masks/{name}.nii.gz': sha256(data_dir / 'masks' / (name + '.nii.gz')) for name in NAMES})
    bound = {key.replace('\\', '/'): value for key, value in
             proposal.get('input_provenance', {}).get('input_sha256', {}).items()}
    if bound != current:
        raise ValueError(f'{case}: proposal input hashes do not match current CT/labels')
    landmarks = {}
    for key, lm in proposal.get('landmarks', {}).items():
        point = lm.get('point_lps_mm')
        if point is None:
            continue
        landmarks[key] = {'status': 'confirmed', 'point_lps_mm': point,
                          'review': {'method': 'human', 'reviewer': reviewer,
                                     'reviewed_at': reviewed_at, 'decision': 'accept',
                                     'scope': 'coarse_localization_only',
                                     'source_status': lm.get('status')}}
    if not landmarks:
        raise ValueError(f'{case}: proposal has no usable points')
    return {'case': case, 'patient_id': patient_id(case), 'descriptor': descriptor,
            'landmarks': landmarks,
            'provenance': {'proposal_sha256': sha256(proposal_path),
                           'confirmation_sha256': acceptance_sha256,
                           'acceptance_sha256': acceptance_sha256,
                           'ct_sha256': current['ct.nii.gz'],
                           'input_sha256': current},
            'acceptance_scope': 'coarse_localization_only',
            'coarse_reference_eligible': True,
            'coarse_reference_quality_warning': quality_warning}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', nargs='+', default=['p0', 'p1', 'p2', 'p3', 'p3t1'])
    parser.add_argument('--data-base', type=Path, default=Path('C:/ts_work'))
    parser.add_argument('--proposal-base', type=Path,
                        default=Path(__file__).resolve().parents[1] / '06_auto_landmarks')
    parser.add_argument('--library', type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument('--reviewer', default='human-accepted coarse reference')
    parser.add_argument('--reviewed-at', default=datetime.now().astimezone().isoformat(timespec='seconds'))
    parser.add_argument('--acceptance-record', type=Path,
                        default=Path(__file__).resolve().parents[1] / '06_auto_landmarks' / 'coarse_reference_acceptance.json')
    args = parser.parse_args(argv)
    acceptance = {'schema': 'coarse_reference_acceptance/v1',
                  'scope': 'coarse_localization_only',
                  'reviewer': args.reviewer, 'reviewed_at': args.reviewed_at,
                  'statement': 'Existing candidate positions were accepted for coarse initialization; this record does not confirm anatomy or unlock CFD.',
                  'requested_cases': args.cases}
    write_json(args.acceptance_record, acceptance)
    acceptance_digest = sha256(args.acceptance_record)
    entries, skipped = [], []
    for case in args.cases:
        try:
            entries.append(register_case(case, args.data_base, args.proposal_base,
                                         acceptance_digest, args.reviewer, args.reviewed_at))
        except (OSError, ValueError, KeyError) as exc:
            skipped.append({'case': case, 'reason': str(exc)})
    library = {'schema': SCHEMA, 'coordinate_system': 'LPS', 'unit': 'mm',
               'references': entries,
               'acceptance_record': str(args.acceptance_record),
               'acceptance_scope': 'coarse_localization_only',
               'note': 'These references initialize coarse search only; human geometry review and CFD gates remain separate.'}
    validate_library(library)
    write_json(args.library, library)
    write_json(args.library.with_name('coarse_reference_registration.json'),
               {'schema': 'coarse_reference_registration/v1', 'library': str(args.library),
                'accepted_cases': [e['case'] for e in entries], 'skipped_cases': skipped,
                'acceptance_record_sha256': acceptance_digest,
                'scope': 'coarse_localization_only'})
    print({'accepted': [e['case'] for e in entries], 'skipped': skipped,
            'library': str(args.library), 'acceptance_record_sha256': acceptance_digest})
    return 0 if entries else 1


if __name__ == '__main__':
    raise SystemExit(main())
