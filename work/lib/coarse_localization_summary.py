"""Read-only coarse/refined evidence shared by the dashboard and CT runner."""
from __future__ import annotations

import math


def summarize_localization(report):
    prior = report.get('coarse_localization') or {}
    adjustment = report.get('coarse_adjustment') or {}
    valid = (prior.get('schema') == 'coarse_anatomy_prior/v1'
             and prior.get('coordinate_system') == 'LPS' and prior.get('unit') == 'mm')
    references = prior.get('accepted_references', []) if valid else []
    points = prior.get('landmarks', {}) if valid else {}
    refined = report.get('landmarks', {})
    deltas = []
    local, fallback, outside = [], [], []
    for key, point in refined.items():
        evidence = point.get('evidence') or {}
        variants = [evidence, *(evidence.get('threshold_variants') or [])]
        modes = {v.get('search_mode') for v in variants if isinstance(v, dict)}
        if 'coarse_prior_local_search' in modes:
            local.append(key)
        if 'global_fallback_after_local_search' in modes:
            fallback.append(key)
        if (point.get('consistency_checks') or {}).get('within_coarse_search_box') is False:
            outside.append(key)
    if (valid and adjustment.get('schema') == 'coarse_anatomy_adjustment/v1'
            and adjustment.get('case') == report.get('case')
            and adjustment.get('reference_library_sha256') == prior.get('reference_library_sha256')):
        for key, item in adjustment.get('landmarks', {}).items():
            # A missing CT candidate never contributes an apparent displacement.
            if (refined.get(key, {}).get('point_lps_mm') is None
                    or not item.get('coarse') or not item.get('refined')):
                continue
            distance = (item.get('delta') or {}).get('distance_uas_mm')
            if (type(distance) in (int, float) and math.isfinite(distance) and distance >= 0):
                deltas.append(distance)
    search_count = sum(p.get('status') == 'search_prior' for p in points.values())
    descriptor = prior.get('target_descriptor') or {}
    return {
        'schema': 'coarse_localization_summary/v1',
        'status': ('search_prior' if search_count else 'display_only' if points
                   else 'unavailable' if valid else 'not_generated'),
        'search_prior_points': search_count,
        'display_only_points': sum(p.get('status') == 'display_only' for p in points.values()),
        'outside_ct_points': sum(p.get('status') == 'outside_ct' for p in points.values()),
        'reference_cases': [r['case'] for r in references],
        'reference_quality_warnings': [{'case': r['case'], 'reason': r['quality_warning']}
                                       for r in references if r.get('quality_warning')],
        'independent_reference_patients': len({r['patient_id'] for r in references}),
        'reference_library_sha256': prior.get('reference_library_sha256') if valid else None,
        'local_search_landmarks': local, 'fallback_landmarks': fallback,
        'outside_search_box_landmarks': outside,
        'max_refinement_delta_mm': max(deltas) if deltas else None,
        'compared_points': len(deltas),
        'palate_rms_mm': (descriptor.get('frame', {}).get('palate_fit') or {}).get('rms_mm'),
        'reason': prior.get('reason') if valid else None,
        'clinical_acceptance': False,
    }
