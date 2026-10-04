"""Transfer reviewed points by anatomical bounds; proposals, never CT deformation.

The frame removes head pose. Bounds come from bilateral nasal labels, not the
scan box. Independent patient medians prevent repeated scans gaining weight.
All distances are physical millimetres. Limits below are engineering settings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from numbers import Real
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LIBRARY = ROOT / 'work' / '06_auto_landmarks' / 'reference_library.json'
SCHEMA = 'coarse_anatomy_reference_library/v1'
UNIFIED_COORDINATE_SYSTEM = 'UAS'
NORMALIZED_COORDINATE_SYSTEM = 'UAS-NORM'
ADJUSTMENT_SCHEMA = 'coarse_anatomy_adjustment/v1'
LANDMARKS = ('nostril_L', 'nostril_R', 'posterior_choana_L',
             'posterior_choana_R', 'nasopharynx_outlet')
FRAME_LABELS = ('nasal_cavity_left', 'nasal_cavity_right', 'hard_palate', 'nasopharynx')
PARAMETERS = {'bounds_quantiles': [.005, .995], 'scale_range': [.7, 1.4],
              'minimum_independent_patients': 2, 'search_margin_mm': 10.,
              'maximum_reference_spread_mm': 12., 'minimum_span_mm': 1.,
              'maximum_palate_rms_mm': 1.5,
              'note': 'Engineering settings; search boxes are not confidence intervals.'}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    def reject_constant(value):
        raise ValueError('Non-finite JSON number: ' + value)
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), parse_constant=reject_constant)


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def patient_id(case):
    # Known fixture timepoints belong to one patient. New cases need an explicit
    # anonymous group to recognize different scans of the same person.
    return 'p3' if case == 'p3t1' else case


def basis(frame):
    axes = np.column_stack([frame[k] for k in ('left_lps', 'posterior_lps', 'superior_lps')])
    origin = vector(frame['origin_lps_mm'])
    if (axes.shape != (3, 3) or not np.isfinite(axes).all()
            or not np.allclose(axes.T @ axes, np.eye(3), atol=1e-5)
            or np.linalg.det(axes) < .99):
        raise ValueError('Invalid anatomical left/posterior/superior frame')
    return origin, axes


def vector(value):
    arr = np.asarray(value, dtype=float)
    if (arr.shape != (3,) or not np.isfinite(arr).all()
            or any(isinstance(v, bool) or not isinstance(v, Real) for v in value)):
        raise ValueError('Expected three finite numeric coordinates')
    return arr


def to_local(points, frame):
    origin, axes = basis(frame)
    return (np.asarray(points) - origin) @ axes


def to_lps(points, frame):
    origin, axes = basis(frame)
    return np.asarray(points) @ axes.T + origin


def unified_frame(frame):
    """Serializable transform for the project anatomical coordinate system."""
    origin, axes = basis(frame)
    return {'schema': 'unified_anatomical_frame/v1',
            'coordinate_system': UNIFIED_COORDINATE_SYSTEM, 'unit': 'mm',
            'axis_labels': ['patient_left', 'posterior', 'superior'],
            'origin_lps_mm': origin.tolist(),
            'axes_lps_columns': axes.tolist(),
            'lps_to_uas_matrix': axes.T.tolist(),
            'uas_to_lps_matrix': axes.tolist(),
            'origin_definition': frame.get('origin_definition'),
            'source_frame': frame}


def normalize_uas(points, descriptor):
    local = np.asarray(points, dtype=float)
    low = vector(descriptor['local_bounds_mm']['min'])
    span = vector(descriptor['span_mm'])
    return (local - low) / span


def denormalize_uas(points, descriptor):
    low = vector(descriptor['local_bounds_mm']['min'])
    span = vector(descriptor['span_mm'])
    return np.asarray(points, dtype=float) * span + low


def point_coordinates(point_lps, descriptor):
    """Return LPS, UAS-mm and normalized UAS coordinates for one point."""
    point = vector(point_lps)
    uas = to_local(point, descriptor['frame'])
    return {'point_lps_mm': point.tolist(), 'point_uas_mm': uas.tolist(),
            'point_uas_normalized': normalize_uas(uas, descriptor).tolist(),
            'coordinate_systems': {'lps': 'LPS', 'unified': UNIFIED_COORDINATE_SYSTEM,
                                   'normalized': NORMALIZED_COORDINATE_SYSTEM}}


def box_corners(box):
    low, high = vector(box['min']), vector(box['max'])
    return np.asarray([[x, y, z] for x in (low[0], high[0])
                       for y in (low[1], high[1])
                       for z in (low[2], high[2])], dtype=float)


def box_coordinates(box, descriptor):
    uas_low = vector(box['min'])
    uas_high = vector(box['max'])
    corners_lps = to_lps(box_corners(box), descriptor['frame'])
    return {'coordinate_system': UNIFIED_COORDINATE_SYSTEM, 'unit': 'mm',
            'min_uas_mm': uas_low.tolist(), 'max_uas_mm': uas_high.tolist(),
            'min_lps_mm': corners_lps.min(axis=0).tolist(),
            'max_lps_mm': corners_lps.max(axis=0).tolist(),
            'corners_lps_mm': corners_lps.tolist()}


def build_coarse_adjustment(case, target_descriptor, prior, landmarks):
    """Bind coarse coordinates to refined CT candidates without changing either."""
    target_frame = unified_frame(target_descriptor['frame'])
    result = {'schema': ADJUSTMENT_SCHEMA, 'case': case,
              'source_coordinate_system': 'LPS',
              'unified_coordinate_system': UNIFIED_COORDINATE_SYSTEM,
              'normalized_coordinate_system': NORMALIZED_COORDINATE_SYSTEM,
              'unit': 'mm', 'normalization_unit': 'ratio_0_to_1',
              'target_frame': target_frame,
              'target_descriptor': {'local_bounds_uas_mm': target_descriptor['local_bounds_mm'],
                                    'span_uas_mm': target_descriptor['span_mm'],
                                    'exact_extrema_uas_mm': target_descriptor['exact_extrema_local_mm'],
                                    'exact_extrema_lps_mm': target_descriptor['exact_extrema_lps_mm'],
                                    'fov_truncated_labels': target_descriptor['fov_truncated_labels'],
                                    'eligible': target_descriptor['eligible'],
                                    'reasons': target_descriptor['reasons']},
              'reference_library_sha256': prior.get('reference_library_sha256'),
              'reviewed_reference_count': prior.get('reviewed_reference_count', 0),
              'accepted_references': prior.get('accepted_references', []),
              'excluded_references': prior.get('excluded_references', []),
              'status': 'available' if prior.get('landmarks') else 'unavailable',
              'landmarks': {},
              'note': 'Coarse positions initialize local search; refined CT candidates remain authoritative proposals.'}
    for key in LANDMARKS:
        rough = prior.get('landmarks', {}).get(key)
        refined = landmarks.get(key, {})
        item = {'coarse': None, 'refined': None, 'delta': None}
        if rough and rough.get('point_lps_mm') is not None:
            coarse = point_coordinates(rough['point_lps_mm'], target_descriptor)
            coarse['status'] = rough.get('status')
            coarse['independent_patients'] = rough.get('independent_patients')
            coarse['reference_spread_uas_mm'] = rough.get('reference_spread_local_mm')
            if rough.get('local_search_box_mm'):
                coarse['search_box_uas'] = box_coordinates(rough['local_search_box_mm'], target_descriptor)
            item['coarse'] = coarse
        if refined.get('point_lps_mm') is not None:
            final = point_coordinates(refined['point_lps_mm'], target_descriptor)
            final['status'] = refined.get('status')
            final['normal_lps'] = refined.get('normal_lps')
            if refined.get('normal_lps') is not None:
                final['normal_uas'] = to_local(vector(refined['normal_lps']),
                                               {'origin_lps_mm': [0., 0., 0.],
                                                'left_lps': target_descriptor['frame']['left_lps'],
                                                'posterior_lps': target_descriptor['frame']['posterior_lps'],
                                                'superior_lps': target_descriptor['frame']['superior_lps']}).tolist()
            item['refined'] = final
        if item['coarse'] and item['refined']:
            delta_lps = vector(item['refined']['point_lps_mm']) - vector(item['coarse']['point_lps_mm'])
            delta_uas = vector(item['refined']['point_uas_mm']) - vector(item['coarse']['point_uas_mm'])
            item['delta'] = {'delta_lps_mm': delta_lps.tolist(),
                             'delta_uas_mm': delta_uas.tolist(),
                             'distance_mm': float(np.linalg.norm(delta_lps)),
                             'distance_uas_mm': float(np.linalg.norm(delta_uas))}
        result['landmarks'][key] = item
    return result


def describe(masks, a, frame, truncated):
    """Exact extrema and outlier-resistant bounds of the same named structure."""
    from auto_anatomy_landmarks import physical
    points = physical(np.argwhere(masks['nasal_cavity_left'] | masks['nasal_cavity_right']), a)
    if len(points) < 50:
        raise ValueError('Too few nasal voxels for a coarse reference')
    local = to_local(points, frame)
    low, high = np.quantile(local, PARAMETERS['bounds_quantiles'], axis=0)
    span = high - low
    reasons = [name + ': label touches CT boundary' for name in FRAME_LABELS if truncated.get(name, True)]
    if np.any(span < PARAMETERS['minimum_span_mm']):
        reasons.append('Degenerate anatomical span')
    if frame.get('palate_fit', {}).get('rms_mm', float('inf')) > PARAMETERS['maximum_palate_rms_mm']:
        reasons.append('Palate frame residual exceeds engineering setting')
    return {'schema': 'coarse_anatomy_descriptor/v1', 'coordinate_system': 'LPS', 'unit': 'mm',
            'frame': frame, 'structure': 'bilateral semantic nasal cavity',
            'unified_frame': unified_frame(frame),
            'axes': ['patient_left', 'posterior', 'superior'],
            'bounds_quantiles': PARAMETERS['bounds_quantiles'],
            'local_bounds_mm': {'min': low.tolist(), 'max': high.tolist()},
            'span_mm': span.tolist(),
            'exact_extrema_local_mm': {'min': local.min(0).tolist(), 'max': local.max(0).tolist()},
            'exact_extrema_lps_mm': {'min': points.min(0).tolist(), 'max': points.max(0).tolist()},
            'fov_truncated_labels': dict(truncated), 'eligible': not reasons, 'reasons': reasons}


def load_descriptor(data):
    """Build the frame from the target CT and labels; no reference coordinates used."""
    import SimpleITK as sitk
    from auto_anatomy_landmarks import NAMES, affine, build_frame, geometry_matches, physical
    data = Path(data)
    image = sitk.ReadImage(str(data / 'ct.nii.gz'))
    masks, truncated, bounds = {}, {}, []
    for name in NAMES:
        mask_img = sitk.ReadImage(str(data / 'masks' / (name + '.nii.gz')))
        if not geometry_matches(image, mask_img):
            raise ValueError(name + ': mask/CT geometry mismatch')
        mask = sitk.GetArrayFromImage(mask_img) > 0
        coords = np.argwhere(mask)
        if not len(coords):
            raise ValueError(name + ': empty reference label')
        low, high = coords.min(0), coords.max(0)
        bounds.append((low, high))
        truncated[name] = bool(np.any(low == 0) or np.any(high == np.asarray(mask.shape) - 1))
        masks[name] = mask
    low = np.min([b[0] for b in bounds], axis=0)
    high = np.max([b[1] for b in bounds], axis=0) + 1
    slices = tuple(slice(x, y) for x, y in zip(low, high))
    masks = {name: mask[slices].copy() for name, mask in masks.items()}
    ct = sitk.GetArrayViewFromImage(image)[slices].astype(np.float32)
    a = affine(image)
    a[:3, 3] = physical(low, a)
    frame = build_frame(masks, ct, a)
    return describe(masks, a, frame, truncated), image


def validate_descriptor(desc, allow_frame_warning=False):
    if (desc.get('schema') != 'coarse_anatomy_descriptor/v1'
            or desc.get('coordinate_system') != 'LPS' or desc.get('unit') != 'mm'
            or desc.get('structure') != 'bilateral semantic nasal cavity'
            or desc.get('bounds_quantiles') != PARAMETERS['bounds_quantiles']):
        raise ValueError('Incompatible coarse descriptor')
    basis(desc['frame'])
    low, high = (vector(desc['local_bounds_mm'][key]) for key in ('min', 'max'))
    span = vector(desc['span_mm'])
    if (np.any(span < PARAMETERS['minimum_span_mm'])
            or not np.allclose(span, high - low, atol=1e-6)):
        raise ValueError('Invalid anatomical bounds/span')
    if desc.get('eligible') is not True and not allow_frame_warning:
        raise ValueError('Reference structure/frame is incomplete')
    if any(desc.get('fov_truncated_labels', {}).get(name, True) for name in FRAME_LABELS):
        raise ValueError('Reference label touches CT boundary')
    if (not allow_frame_warning
            and desc['frame'].get('palate_fit', {}).get('rms_mm', float('inf')) > PARAMETERS['maximum_palate_rms_mm']):
        raise ValueError('Invalid palate frame fit')


def validate_library(library):
    if (library.get('schema') != SCHEMA or library.get('coordinate_system') != 'LPS'
            or library.get('unit') != 'mm' or not isinstance(library.get('references'), list)):
        raise ValueError('Invalid reference library schema/coordinates')
    seen = set()
    for entry in library['references']:
        if not isinstance(entry.get('case'), str) or not entry['case'] or not entry.get('patient_id'):
            raise ValueError('Reference needs case and anonymous patient_id')
        if entry['case'] in seen:
            raise ValueError('Duplicate reference case')
        seen.add(entry['case'])
        allow_warning = (library.get('acceptance_scope') == 'coarse_localization_only'
                         and entry.get('coarse_reference_eligible') is True)
        validate_descriptor(entry['descriptor'], allow_frame_warning=allow_warning)
        provenance = entry.get('provenance', {})
        for key in ('proposal_sha256', 'confirmation_sha256', 'ct_sha256'):
            value = provenance.get(key, '')
            if len(value) != 64 or any(v not in '0123456789abcdef' for v in value):
                raise ValueError('Reference missing content binding: ' + key)
        if not entry.get('landmarks'):
            raise ValueError('Reference has no reviewed landmarks')
        for key, lm in entry['landmarks'].items():
            if key not in LANDMARKS or lm.get('status') != 'confirmed':
                raise ValueError('Reference point is not human confirmed')
            vector(lm['point_lps_mm'])
            review = lm.get('review', {})
            if (review.get('method') != 'human' or not review.get('reviewer')
                    or not review.get('reviewed_at') or review.get('decision') not in ('accept', 'adjust')):
                raise ValueError('Reference needs a dated human review')
    return library


def add_reference(library_path, case, data_dir, proposal_path, confirmation_path, group):
    """Only accept an existing confirmation bound to the exact proposal and CT."""
    from auto_anatomy_landmarks import NAMES
    proposal, confirmation = read_json(proposal_path), read_json(confirmation_path)
    if (proposal.get('case') != case or confirmation.get('case') != case
            or proposal.get('coordinate_system') != 'LPS' or proposal.get('unit') != 'mm'
            or confirmation.get('schema') != 'anatomy_barrier_review/v2'
            or confirmation.get('coordinate_system') != 'LPS' or confirmation.get('unit') != 'mm'
            or confirmation.get('source_sha256') != sha256(proposal_path)):
        raise ValueError('Confirmation does not bind to the exact LPS/mm proposal')
    data = Path(data_dir)
    current_inputs = {'ct.nii.gz': sha256(data / 'ct.nii.gz')}
    current_inputs.update({f'masks/{name}.nii.gz': sha256(data / 'masks' / (name + '.nii.gz')) for name in NAMES})
    bound = {key.replace('\\', '/'): value for key, value in
             proposal.get('input_provenance', {}).get('input_sha256', {}).items()}
    if bound != current_inputs:
        raise ValueError('CT/labels differ from the human-reviewed proposal inputs')
    descriptor, _ = load_descriptor(data)
    validate_descriptor(descriptor)
    landmarks = {}
    for key in LANDMARKS:
        plane = confirmation.get('planes_lps', {}).get(key, {})
        if plane.get('status') != 'confirmed':
            continue
        if (key == 'nasopharynx_outlet' and any(descriptor['fov_truncated_labels'].get(n, True)
                                               for n in ('soft_palate', 'oropharynx'))):
            continue
        point = vector(plane['point_lps_mm'])
        review = plane.get('review', {})
        source = proposal.get('landmarks', {}).get(key, {}).get('point_lps_mm')
        if source is None or (review.get('decision') == 'accept' and not np.allclose(point, vector(source), atol=1e-8)):
            raise ValueError('Accepted reference point differs from reviewed proposal')
        landmarks[key] = {'status': 'confirmed', 'point_lps_mm': point.tolist(), 'review': review}
    entry = {'case': case, 'patient_id': group, 'descriptor': descriptor, 'landmarks': landmarks,
             'provenance': {'proposal_sha256': sha256(proposal_path),
                            'confirmation_sha256': sha256(confirmation_path),
                            'ct_sha256': current_inputs['ct.nii.gz'], 'input_sha256': current_inputs}}
    path = Path(library_path)
    library = validate_library(read_json(path)) if path.is_file() else {
        'schema': SCHEMA, 'coordinate_system': 'LPS', 'unit': 'mm', 'references': []}
    library['references'] = [ref for ref in library['references'] if ref['case'] != case] + [entry]
    validate_library(library)
    write_json(path, library)
    return entry


def transfer(point, source, target):
    """Three independent size ratios plus pose and translation, applied to points."""
    u = (to_local(vector(point), source['frame']) - vector(source['local_bounds_mm']['min'])) / vector(source['span_mm'])
    local = vector(target['local_bounds_mm']['min']) + u * vector(target['span_mm'])
    return to_lps(local, target['frame'])


def predict(target, references, case, group, ct_hash, image=None):
    """Equal weight per person, with exclusion and engineering applicability checks."""
    result = {'schema': 'coarse_anatomy_prior/v1', 'coordinate_system': 'LPS', 'unit': 'mm',
              'status': 'unavailable', 'target_descriptor': target, 'parameters': PARAMETERS,
              'accepted_references': [], 'excluded_references': [], 'landmarks': {},
              'purpose': 'Initial search position only; target CT evidence remains required.'}
    if not target.get('eligible'):
        result['reason'] = 'Target structure/frame incomplete: ' + '; '.join(target['reasons'])
        return result
    validate_descriptor(target)
    estimates = {key: {} for key in LANDMARKS}
    for ref in references:
        reason = None
        if ref['case'] == case or ref['patient_id'] == group or ref['provenance']['ct_sha256'] == ct_hash:
            reason = 'same case, patient or CT content'
        elif not (ref['descriptor'].get('eligible') or ref.get('coarse_reference_eligible')):
            reason = 'incomplete reference structure/frame'
        ratio = vector(target['span_mm']) / vector(ref['descriptor']['span_mm'])
        if reason is None and (np.any(ratio < PARAMETERS['scale_range'][0]) or np.any(ratio > PARAMETERS['scale_range'][1])):
            reason = 'size ratios outside engineering range'
        if reason:
            result['excluded_references'].append({'case': ref['case'], 'reason': reason})
            continue
        result['accepted_references'].append({'case': ref['case'], 'patient_id': ref['patient_id'],
                                              'scale_left_posterior_superior': ratio.tolist(),
                                              'quality_warning': ref.get('coarse_reference_quality_warning')})
        for key, lm in ref['landmarks'].items():
            if key == 'nasopharynx_outlet' and any(target['fov_truncated_labels'].get(n, True) or
                    ref['descriptor']['fov_truncated_labels'].get(n, True) for n in ('soft_palate', 'oropharynx')):
                continue
            point = transfer(lm['point_lps_mm'], ref['descriptor'], target)
            estimates[key].setdefault(ref['patient_id'], []).append(point)
    for key, groups in estimates.items():
        if not groups:
            continue
        people_local = np.array([np.median(to_local(points, target['frame']), axis=0) for points in groups.values()])
        # Median in the anatomical frame is equivariant under head rotation.
        center_local = np.median(people_local, axis=0)
        center = to_lps(center_local, target['frame'])
        spread = np.max(np.abs(people_local - center_local), axis=0)
        half = PARAMETERS['search_margin_mm'] + spread
        usable = (len(groups) >= PARAMETERS['minimum_independent_patients']
                  and np.linalg.norm(spread) <= PARAMETERS['maximum_reference_spread_mm'])
        index = np.asarray(image.TransformPhysicalPointToContinuousIndex(tuple(center))) if image is not None else None
        outside = index is not None and np.any((index < 0) | (index > np.asarray(image.GetSize()) - 1))
        lm = {'point_lps_mm': center.tolist(), 'independent_patients': len(groups),
              'reference_spread_local_mm': spread.tolist(),
              'status': 'search_prior' if usable and not outside else 'display_only',
              'local_search_box_mm': {'min': (center_local - half).tolist(), 'max': (center_local + half).tolist()},
              'normal_lps': None, 'clinical_validation': 'not_validated', 'confidence_probability': None}
        coords = point_coordinates(center, target)
        lm.update({'point_uas_mm': coords['point_uas_mm'],
                   'point_uas_normalized': coords['point_uas_normalized'],
                   'search_box_uas_mm': lm['local_search_box_mm']})
        if outside:
            lm['status'] = 'outside_ct'
        result['landmarks'][key] = lm
    result['status'] = 'available' if result['landmarks'] else 'unavailable'
    if not result['landmarks']:
        result['reason'] = 'No compatible independent reviewed references'
    return result


def build_prior(target, library_path, case, group, ct_hash, image=None):
    path = Path(library_path)
    if not path.is_file():
        library, digest, error = {'references': []}, None, 'Reference library missing'
    else:
        digest = sha256(path)
        try:
            library, error = validate_library(read_json(path)), None
        except (ValueError, KeyError, TypeError) as exc:
            library, error = {'references': []}, 'Invalid reference library: ' + str(exc)
    result = predict(target, library['references'], case, group, ct_hash, image)
    result['reference_library_sha256'] = digest
    result['reviewed_reference_count'] = len(library['references'])
    if error:
        result['reason'] = error
    return result


def in_search_box(points, prior, frame):
    box = prior['local_search_box_mm']
    local = to_local(points, frame)
    return np.all((local >= vector(box['min'])) & (local <= vector(box['max'])), axis=-1)


def compare_candidates(prior, landmarks, frame):
    for key, lm in landmarks.items():
        rough = prior['landmarks'].get(key)
        if rough is None:
            continue
        lm['coarse_prior'] = rough
        if lm['point_lps_mm'] is None:
            continue  # Missing image evidence is never replaced by a template point.
        distance = float(np.linalg.norm(vector(lm['point_lps_mm']) - vector(rough['point_lps_mm'])))
        lm['evidence']['distance_from_coarse_prior_mm'] = distance
        if rough['status'] == 'search_prior':
            inside = bool(in_search_box(vector(lm['point_lps_mm']), rough, frame))
            lm['consistency_checks']['within_coarse_search_box'] = inside
            if not inside:
                lm['status'] = 'needs_review'
                lm['review_reasons'].append('本例影像候选超出标准病例粗定位范围，需检查结构差异与预设适用性')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True)
    parser.add_argument('--patient-id', required=True, help='Anonymous patient group; same person uses the same value')
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--proposal', required=True, type=Path)
    parser.add_argument('--confirmed', required=True, type=Path)
    parser.add_argument('--library', default=DEFAULT_LIBRARY, type=Path)
    args = parser.parse_args()
    entry = add_reference(args.library, args.case, args.data_dir, args.proposal, args.confirmed, args.patient_id)
    print(json.dumps({'case': args.case, 'reviewed_points_added': list(entry['landmarks']),
                      'library': str(args.library)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
