"""The placement search origin, tested on both sides.

Why this exists: b05/b15/b18 fail at stage 5 because the search coordinate is
measured from the lumen onset, whose detection threshold is AREA_ON = 50 mm2,
while the cap target is 80/250. The plane then starts 1.25-3.25 mm behind the
proposed plane, where the ROI box (which travels with the plane) no longer holds
a single negative-side vertex. Measured: b15 outlet onset -1.75 -> 0 seeds,
b18 -3.25 -> 0 seeds, while at the proposed plane itself they clip cleanly at
439.18 and 251.64 mm2.

'origin=reviewed' removes that coupling: the coordinate is measured from the
proposed plane and starts ON it (START_OFFSET_MM), because on b15 the outlet cap
at proposed+0.5 mm is already 682.23 mm2 - past the 500 mm2 band ceiling - while
at proposed+0.0 it is 439.18 and in band.

The historical origin stays the default and must stay bit-identical, which the
first test pins.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_opening_pipeline as A

SURF_B15 = Path('C:/ts_work/batch27_surfaces/b15/source_surface.vtp')
LM_B15 = Path('D:/项目/鼻腔建模/work/06_auto_landmarks/b15/landmarks.json')
SURF_B08 = Path('C:/ts_work/batch27_surfaces/b08/source_surface.vtp')
LM_B08 = Path('D:/项目/鼻腔建模/work/06_auto_landmarks/b08/landmarks.json')


def _load(surface, landmarks):
    import json

    import vtk
    from export_candidate_preview import triangle_arrays

    obj = json.loads(landmarks.read_text(encoding='utf-8'))
    reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(str(surface))
    reader.Update()
    points, faces = triangle_arrays(reader.GetOutput())
    planes = {n: {'point_lps_mm': obj['landmarks'][n]['point_lps_mm'],
                  'normal_lps': obj['landmarks'][n]['normal_lps'],
                  'roi_lps_mm': obj['landmarks'][n]['roi_lps_mm'],
                  'keep_positive': True} for n in A.OPENINGS}
    return points, faces, planes


def test_onset_origin_returns_the_onsets():
    onsets = {'nostril_L': -0.25, 'nostril_R': 0.0, 'nasopharynx_outlet': -1.75}
    assert A.search_base(onsets, 'onset') == onsets


def test_reviewed_origin_zeroes_the_base():
    onsets = {'nostril_L': -0.25, 'nostril_R': 0.0, 'nasopharynx_outlet': -1.75}
    assert A.search_base(onsets, 'reviewed') == {k: 0.0 for k in onsets}


def test_unknown_origin_is_refused():
    with pytest.raises(ValueError):
        A.search_base({k: 0.0 for k in A.OPENINGS}, 'nonsense')


def test_default_origin_is_the_historical_one():
    assert A.SEARCH_ORIGINS[0] == 'onset'
    assert A.START_OFFSET_MM['onset'] == A.SEED_OFFSET_MM
    assert A.START_OFFSET_MM['reviewed'] == 0.0


def test_base_and_offset_compose_into_one_translation():
    spec = {'point_lps_mm': [0., 0., 0.], 'normal_lps': [0., 0., 1.],
            'roi_lps_mm': {'min': [-1., -1., -1.], 'max': [1., 1., 1.]},
            'keep_positive': True}
    placed = A.place(spec, np.array([0., 0., 1.]), 2.0)
    assert placed['point_lps_mm'] == [0., 0., 2.]
    assert placed['roi_lps_mm']['max'] == [1., 1., 3.]
    planes = {k: spec for k in A.OPENINGS}
    norms = {k: np.array([0., 0., 1.]) for k in A.OPENINGS}
    built = A.build_placed(planes, norms, {k: 1.0 for k in A.OPENINGS},
                           {k: 2.0 for k in A.OPENINGS})
    first = A.OPENINGS[0]
    assert built[first]['point_lps_mm'] == [0., 0., 3.]


def test_diag_reports_the_origin_and_base():
    points = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]])
    faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])
    planes = {k: {'point_lps_mm': [100., 100., 100.], 'normal_lps': [0., 0., 1.],
                  'roi_lps_mm': {'min': [99., 99., 99.], 'max': [101., 101., 101.]},
                  'keep_positive': True} for k in A.OPENINGS}
    norms = {k: np.array([0., 0., 1.]) for k in A.OPENINGS}
    onsets = {k: -2.5 for k in A.OPENINGS}
    _, _, diag = A.solve_placement(points, faces, planes, norms, onsets, 'roi',
                                   'reviewed')
    assert diag['search_origin'] == 'reviewed'
    assert diag['base_offset_mm'] == {k: 0.0 for k in A.OPENINGS}


def test_search_window_is_per_origin():
    """The reviewed window must stay inside the geometry that can be clipped.

    Measured on b15/b18 (probe_cap_vs_push.py): the clipper starts refusing
    placements past roughly +2 mm from the reviewed plane, and the 18 passing
    cases travel at most 0.97 mm (mean 0.20 mm). 3 mm therefore covers three
    times the largest observed travel while staying clear of the refusal zone.
    The onset window is unchanged at the historical 14 mm.
    """
    assert A.SEARCH_HI_BY_ORIGIN['onset'] == A.SEARCH_HI_MM == 14.0
    assert A.SEARCH_HI_BY_ORIGIN['reviewed'] == 3.0
    assert A.SEARCH_HI_BY_ORIGIN['reviewed'] < A.SEARCH_HI_BY_ORIGIN['onset']


def test_diag_reports_the_window_actually_used():
    points = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]])
    faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])
    planes = {k: {'point_lps_mm': [100., 100., 100.], 'normal_lps': [0., 0., 1.],
                  'roi_lps_mm': {'min': [99., 99., 99.], 'max': [101., 101., 101.]},
                  'keep_positive': True} for k in A.OPENINGS}
    norms = {k: np.array([0., 0., 1.]) for k in A.OPENINGS}
    onsets = {k: -2.5 for k in A.OPENINGS}
    _, _, diag = A.solve_placement(points, faces, planes, norms, onsets, 'roi',
                                   'reviewed')
    assert diag['search_window_mm'] == 3.0


@pytest.mark.skipif(not SURF_B15.exists() or not LM_B15.exists(),
                    reason='b15 surface or landmarks not present')
def test_reviewed_origin_recovers_b15_where_the_onset_origin_loses_the_seed():
    """Both sides of the change, on the case that motivated it.

    onset origin -> seed_lost at the outlet (the shipped failure), unchanged.
    reviewed origin -> the plane stays on the proposal and the case passes with
    the outlet cap the proposal position actually produces.
    """
    import json

    import vtk
    from export_candidate_preview import triangle_arrays

    obj = json.loads(LM_B15.read_text(encoding='utf-8'))
    reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(str(SURF_B15))
    reader.Update()
    points, faces = triangle_arrays(reader.GetOutput())
    planes = {n: {'point_lps_mm': obj['landmarks'][n]['point_lps_mm'],
                  'normal_lps': obj['landmarks'][n]['normal_lps'],
                  'roi_lps_mm': obj['landmarks'][n]['roi_lps_mm'],
                  'keep_positive': True} for n in A.OPENINGS}
    # The shipped failure, in the default seeding mode: with the plane pushed
    # to onset+0.5 the ROI box holds no negative-side vertex at all.
    old = A.process('b15', points, faces, {'planes_lps': planes},
                    Path('.tools/test_search_origin'), origin='onset', seed_mode='roi')
    assert old['decision'] == 'escalated'
    assert [e['reason'] for e in old['escalations']] == ['seed_lost']

    new = A.process('b15', points, faces, {'planes_lps': planes},
                    Path('.tools/test_search_origin'), origin='reviewed')
    assert new['decision'] == 'auto_pass', new['escalations']
    areas = new['patch_areas_mm2']
    for name, (lo, hi) in A.AREA_BAND_MM2.items():
        assert lo <= areas[name] <= hi, (name, areas[name])
    # the outlet needs no travel at all (439.18 at the proposal, target 250)
    assert new['offset_from_reviewed_mm']['nasopharynx_outlet'] == 0.0
    assert areas['nasopharynx_outlet'] == pytest.approx(439.18, abs=0.01)
    # ...while both nostrils sit just under the 80 mm2 target at the proposal
    # (67.86 / 72.54) and travel a fraction of a millimetre to reach it
    for name in ('nostril_L', 'nostril_R'):
        assert 0.0 < new['offset_from_reviewed_mm'][name] < 1.0
        assert areas[name] == pytest.approx(80.0, abs=1.0)


@pytest.mark.skipif(not SURF_B08.exists() or not LM_B08.exists(),
                    reason='b08 surface or landmarks not present')
def test_reviewed_anchor_above_the_ceiling_downgrades_and_says_so():
    """The other side of the anchor assumption: b08's reviewed plane is too deep.

    At the reviewed plane b08's outlet cap is 772.35 mm2 against a 500 mm2
    ceiling - the reviewed point sits 1.5 mm inside where the onset search had
    placed the plane, in the wide part of the nasopharynx. An anchor that is
    itself out of band is not a starting position, so the search must fall back
    to the onset origin AND record the downgrade, because a silent fallback
    would hide a landmark problem behind a passing number.
    """
    points, faces, planes = _load(SURF_B08, LM_B08)

    rep = A.process('b08', points, faces, {'planes_lps': planes},
                    Path('.tools/test_search_origin'), origin='reviewed')

    # the downgrade is recorded, with the offending area
    dg = rep['origin_downgrade']
    assert dg['requested_origin'] == 'reviewed'
    assert dg['used_origin'] == 'onset'
    assert dg['reason'] == 'anchor_cap_above_band_ceiling'
    assert dg['openings_mm2']['nasopharynx_outlet'] == pytest.approx(772.35, abs=0.5)
    # the report says which origin actually ran
    assert rep['requested_search_origin'] == 'reviewed'
    assert rep['search_origin'] == 'onset'
    assert rep['search_window_mm'] == A.SEARCH_HI_BY_ORIGIN['onset']
    # and the case lands back inside the band, at the baseline value
    assert rep['decision'] == 'auto_pass', rep['escalations']
    assert rep['patch_areas_mm2']['nasopharynx_outlet'] == pytest.approx(254.71, abs=0.5)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
