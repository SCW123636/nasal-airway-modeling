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
    # Only the nostrils come from landmarks. The oropharynx_truncation_outlet has
    # no landmark since T-058: the domain ends at the scan's inferior face, so
    # its plane is derived from the air mask by truncation_plane() and injected
    # by the caller. The landmark file still carries a nasopharynx_outlet
    # proposal; it is kept as a diagnostic but no longer consumed as the outlet.
    assert set(planes) == {'nostril_L', 'nostril_R'}
    assert admitted == []


def test_needs_review_is_refused_by_default(tmp_path):
    write_case(tmp_path, 'needs_review')
    with pytest.raises(ValueError, match='needs_review'):
        load_planes(tmp_path, None, 'cx')


def test_needs_review_is_admitted_when_asked_and_recorded(tmp_path):
    write_case(tmp_path, 'needs_review')
    planes, provenance, sha, admitted = load_planes(
        tmp_path, None, 'cx', allow_needs_review=True)
    assert set(planes) == {'nostril_L', 'nostril_R'}
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
    """b02 is the case whose OUTLET is flagged - the historical 22/24 failure.

    That flag is no longer consumed: since T-058 the outlet plane is derived from
    the air mask, not from the landmark, so a flag on the nasopharynx_outlet
    proposal cannot block placement. This test pins the new behaviour and keeps
    the old finding legible instead of deleting it:

      * the default path now loads b02 (its nostrils are proposed, unflagged)
      * the outlet landmark is still present in the file - not deleted, so the
        diagnostic survives - it is simply not a plane source any more
    """
    planes, _, _, admitted = load_planes(PROPOSALS, None, 'b02')
    assert set(planes) == {'nostril_L', 'nostril_R'}
    assert admitted == []
    obj = json.loads((PROPOSALS / 'b02' / 'landmarks.json').read_text(encoding='utf-8'))
    assert 'nasopharynx_outlet' in obj['landmarks']
    assert obj['landmarks']['nasopharynx_outlet'].get('status') == 'needs_review'
