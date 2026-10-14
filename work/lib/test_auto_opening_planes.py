"""Exercise the plane-loader gate, including the needs_review branch.

Why this test exists: on 2026-10-12 the b01-b24 batch came back 2/24, and all 22
failures were the same `no_planes` escalation raised by `load_planes` rejecting a
`needs_review` proposal. That flag turned out to carry no information about point
quality (see auto_opening_pipeline.load_planes). Four criteria in this project
have already shipped broken while their output looked plausible, so the opt-in
branch added to fix it gets a test on both sides:

  * the default path must still refuse a needs_review proposal
  * the opt-in path must admit it AND record what it admitted
  * a genuinely unusable proposal (no point at all) must fail even with the flag

The last one matters most: the flag admits a *flag*, not an absence.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auto_opening_pipeline import load_planes

PROPOSALS = Path('D:/项目/鼻腔建模/work/06_auto_landmarks')


def write_case(root, status, point=True, normals=True):
    d = root / 'cx'
    d.mkdir(parents=True, exist_ok=True)
    lm = {}
    for name in ('nostril_L', 'nostril_R', 'nasopharynx_outlet'):
        lm[name] = {
            'status': status,
            'point_lps_mm': [1.0, 2.0, 3.0] if point else None,
            'normal_lps': [1.0, 0.0, 0.0] if normals else None,
            'roi_lps_mm': {'min': [0, 0, 0], 'max': [5, 5, 5]},
            'review_reasons': ['synthetic'],
        }
    (d / 'landmarks.json').write_text(
        json.dumps({'case': 'cx', 'landmarks': lm}), encoding='utf-8')


def test_proposed_passes_by_default(tmp_path):
    write_case(tmp_path, 'proposed')
    planes, provenance, sha, admitted = load_planes(tmp_path, None, 'cx')
    assert provenance == 'automatic_proposal'
    assert set(planes) == {'nostril_L', 'nostril_R', 'nasopharynx_outlet'}
    assert admitted == []


def test_needs_review_is_refused_by_default(tmp_path):
    write_case(tmp_path, 'needs_review')
    with pytest.raises(ValueError, match='needs_review'):
        load_planes(tmp_path, None, 'cx')


def test_needs_review_is_admitted_when_asked_and_recorded(tmp_path):
    write_case(tmp_path, 'needs_review')
    planes, provenance, sha, admitted = load_planes(
        tmp_path, None, 'cx', allow_needs_review=True)
    assert set(planes) == {'nostril_L', 'nostril_R', 'nasopharynx_outlet'}
    # every admitted flag must be visible in the report, not silently dropped
    assert [a['opening'] for a in admitted] == list(planes)
    assert all(a['status'] == 'needs_review' for a in admitted)


def test_flag_does_not_admit_a_missing_point(tmp_path):
    """The flag relaxes a *status*, never an absence."""
    write_case(tmp_path, 'needs_review', point=False)
    with pytest.raises(ValueError, match='no usable'):
        load_planes(tmp_path, None, 'cx', allow_needs_review=True)


def test_unavailable_is_never_admitted(tmp_path):
    for status in ('unavailable', 'needs_more_data'):
        write_case(tmp_path, status)
        with pytest.raises(ValueError):
            load_planes(tmp_path, None, 'cx')
        with pytest.raises(ValueError):
            load_planes(tmp_path, None, 'cx', allow_needs_review=True)


@pytest.mark.skipif(not (PROPOSALS / 'b02' / 'landmarks.json').exists(),
                    reason='cohort proposals not present')
def test_real_cohort_case_matches_the_documented_finding():
    """b02 is the case whose outlet is flagged; a needs_review plane still loads
    under the flag, and the earlier failing default is unchanged."""
    with pytest.raises(ValueError, match='needs_review'):
        load_planes(PROPOSALS, None, 'b02')
    planes, _, _, admitted = load_planes(
        PROPOSALS, None, 'b02', allow_needs_review=True)
    assert set(planes) == {'nostril_L', 'nostril_R', 'nasopharynx_outlet'}
    assert any(a['opening'] == 'nasopharynx_outlet' for a in admitted)
