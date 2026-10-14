"""The placement_unverified gate, tested on both sides.

Why this test exists: on 2026-10-13 the first cut of this gate flagged every
opening that was not `True`, including openings that had never entered a
bisection at all. On b05/b15/b18 that produced three bogus
`placement_unverified` escalations per case, while the true failure (clip_failed
at the starting position) was hidden. That is the fifth instance in this project
of a criterion shipping broken with plausible-looking output, so the tri-state
is pinned here:

  * verified is None when the opening never entered a bisection -> NOT flagged
  * verified is False AND entered is True -> flagged as placement_unverified
  * verified is True -> never flagged

The distinction matters because "we tried and every attempt failed" and "we
never tried" are different claims, and only the first one justifies refusing a
placement.
"""
import sys
from pathlib import Path

import inspect

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_opening_pipeline as A


def test_never_entered_is_not_unverified():
    diag = {
        'weak_probes': {k: 0 for k in A.OPENINGS},
        'verified': {k: None for k in A.OPENINGS},
        'entered_bisection': {k: False for k in A.OPENINGS},
    }
    flagged = [k for k in A.OPENINGS
               if diag['entered_bisection'][k] and diag['verified'][k] is False]
    assert flagged == []


def test_entered_and_failed_is_flagged():
    diag = {
        'weak_probes': {k: 3 for k in A.OPENINGS},
        'verified': {k: False for k in A.OPENINGS},
        'entered_bisection': {k: True for k in A.OPENINGS},
    }
    flagged = [k for k in A.OPENINGS
               if diag['entered_bisection'][k] and diag['verified'][k] is False]
    assert flagged == list(A.OPENINGS)


def test_verified_is_never_flagged():
    diag = {
        'weak_probes': {k: 2 for k in A.OPENINGS},
        'verified': {k: True for k in A.OPENINGS},
        'entered_bisection': {k: True for k in A.OPENINGS},
    }
    flagged = [k for k in A.OPENINGS
               if diag['entered_bisection'][k] and diag['verified'][k] is False]
    assert flagged == []


def test_mixed_states_flag_only_the_failed_one():
    diag = {
        'weak_probes': {'nostril_L': 0, 'nostril_R': 0, 'nasopharynx_outlet': 4},
        'verified': {'nostril_L': True, 'nostril_R': None, 'nasopharynx_outlet': False},
        'entered_bisection': {'nostril_L': False, 'nostril_R': False,
                              'nasopharynx_outlet': True},
    }
    flagged = [k for k in A.OPENINGS
               if diag['entered_bisection'][k] and diag['verified'][k] is False]
    assert flagged == ['nasopharynx_outlet']


def test_solve_placement_returns_three_state_diag():
    """A degenerate surface forces the starting clip to fail for every opening;
    the diag must say 'never entered', not 'unverified'."""
    # four triangles forming a closed tetrahedron - tiny, clean, but nowhere near
    # the plane/ROI the specs below ask for, so clip_areas refuses at the start
    points = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]])
    faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])
    planes = {k: {'point_lps_mm': [100., 100., 100.], 'normal_lps': [0., 0., 1.],
                  'roi_lps_mm': {'min': [99., 99., 99.], 'max': [101., 101., 101.]},
                  'keep_positive': True} for k in A.OPENINGS}
    norms = {k: np.array([0., 0., 1.]) for k in A.OPENINGS}
    onsets = {k: 0.0 for k in A.OPENINGS}
    # origin stated explicitly: since 2026-10-13 the default is 'reviewed', whose
    # start offset is 0.0. This test is about the three-state diag, not about the
    # default, so pin the historical 'onset' arm to keep asserting its 0.5 mm seed.
    offsets, trace, diag = A.solve_placement(points, faces, planes, norms, onsets,
                                             'roi', origin='onset')
    assert set(diag) >= {'weak_probes', 'verified', 'entered_bisection'}
    for k in A.OPENINGS:
        assert diag['verified'][k] is None
        assert diag['entered_bisection'][k] is False
    assert offsets == {k: A.START_OFFSET_MM['onset'] for k in A.OPENINGS}


def test_default_origin_is_reviewed():
    """The default must be the reviewed anchor, and its start offset must be 0.0 -
    measured: at reviewed+0.5 the b15 outlet cap is already 682.23 mm2, past the
    500 mm2 band ceiling."""
    params = inspect.signature(A.process).parameters
    assert params['origin'].default == 'reviewed'
    assert A.START_OFFSET_MM['reviewed'] == 0.0
    # the onset gate is opt-in off: the default run must not silently demote it
    assert params['allow_onset_outlier'].default is False


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
