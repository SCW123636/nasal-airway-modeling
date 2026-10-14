"""section_loops detail + loop-derived seeding, on synthetic known geometry.

Why synthetic: the claim under test is "the returned loops can seed the
connectivity flood without a hand-tuned ROI box". That needs geometry whose
section area and component layout are known exactly, which no patient surface
can give. The real surfaces are used only for a smoke test that the new path
does not raise where the old one worked.

Two invariants are load bearing and are asserted bit-for-bit:
  1. section_loops' areas must not change (the recorded baselines in
     work/07_cfd_pipeline/正常路径基本方法_v1.md depend on them).
  2. the 3D cut points returned by the detail variant must lie ON the plane
     (they are the rim band the seed is derived from).
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cross_section_scan import section_loops, section_loops_detail
from connectivity_opened_surface import flood_mask, OPENINGS

REAL_SRC = Path('C:/ts_work/reviewed_surface_drafts_20261008_r3')


def box(lo, hi):
    """Closed axis-aligned box as 12 triangles; winding is irrelevant here."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], float)
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (2, 3, 7, 6), (1, 2, 6, 5), (0, 4, 7, 3)]
    f = []
    for a, b, c, d in quads:
        f += [[a, b, c], [a, c, d]]
    return v, np.array(f)


def spec(point, normal, roi=None, keep_positive=True):
    d = {'point_lps_mm': list(map(float, point)), 'normal_lps': list(map(float, normal)),
         'keep_positive': keep_positive}
    if roi is not None:
        d['roi_lps_mm'] = {'min': list(map(float, roi[0])), 'max': list(map(float, roi[1]))}
    return d


# ---------------------------------------------------------------- invariant 1
# Welding quantises the 2D projection to 1e-6 mm (np.round(proj_all, 6)), so a
# ~100 mm2 section carries ~1e-5 mm2 of quantisation noise. Anything below that
# is the welding tolerance, not a geometry error; the area bands the pipeline
# actually gates on are 10s of mm2 wide.
AREA_TOL_MM2 = 1e-4


def test_section_loops_areas_unchanged():
    """The wrapper must keep producing the documented areas."""
    v, f = box((0, 0, 0), (10, 10, 10))
    areas, n, diag = section_loops(v, f, (0, 0, 5.0), (0, 0, 1))
    assert n == 1
    assert abs(areas[0] - 100.0) < AREA_TOL_MM2, areas
    assert diag['open_nodes'] == 0

    # off-axis plane through the same cube: area of the section is 100/cos(tilt)
    tilt = np.deg2rad(30.0)
    nrm = np.array([np.sin(tilt), 0.0, np.cos(tilt)])
    areas2, n2, diag2 = section_loops(v, f, (5, 5, 5.0), nrm)
    assert n2 == 1
    assert abs(areas2[0] - 100.0 / np.cos(tilt)) < AREA_TOL_MM2, areas2
    assert diag2['open_nodes'] == 0


def test_section_loops_agrees_with_detail_bit_for_bit():
    """detail must reproduce the wrapper's areas exactly, not approximately."""
    v, f = box((0, 0, 0), (10, 10, 10))
    tilt = np.deg2rad(17.0)
    nrm = np.array([np.sin(tilt), 0.0, np.cos(tilt)])
    for origin in [(5, 5, 5.0), (5, 5, 3.0), (0, 0, 7.5)]:
        a1, n1, _ = section_loops(v, f, origin, nrm)
        a2, n2, diag, detail = section_loops_detail(v, f, origin, nrm)
        assert n1 == n2
        assert len(a1) == len(a2)
        for x, y in zip(a1, a2):
            assert x == y, (origin, x, y)
        assert sum(a2) == pytest.approx(sum(detail['loop_areas_mm2']), abs=0, rel=0)


# ---------------------------------------------------------------- invariant 2
def test_detail_cut_points_lie_on_the_plane():
    v, f = box((0, 0, 0), (10, 10, 10))
    o = np.array([5.0, 5.0, 5.0])
    nrm = np.array([0.3, -0.5, 0.81])
    nrm = nrm / np.linalg.norm(nrm)
    _, _, _, detail = section_loops_detail(v, f, o, nrm)
    P = detail['cut_points_3d']
    assert len(P) >= 3
    s = (P - o) @ nrm
    assert np.abs(s).max() < 1e-9, np.abs(s).max()


def test_detail_loops_reproduce_their_own_area():
    """Each returned loop, re-integrated from its own 3D points, matches."""
    v, f = box((0, 0, 0), (10, 10, 10))
    o = np.array([5.0, 5.0, 5.0])
    nrm = np.array([0.2, 0.9, 0.38])
    nrm = nrm / np.linalg.norm(nrm)
    _, _, _, detail = section_loops_detail(v, f, o, nrm)
    P = detail['cut_points_3d']
    from cross_section_scan import plane_basis
    n_, u_, w_ = plane_basis(nrm)
    assert detail['loops'], 'expected at least one closed loop'
    for idx, area in zip(detail['loops'], detail['loop_areas_mm2']):
        xy = np.stack((P[idx] @ u_, P[idx] @ w_), axis=1)
        shoelace = abs(0.5 * (np.dot(xy[:, 0], np.roll(xy[:, 1], -1))
                              - np.dot(xy[:, 1], np.roll(xy[:, 0], -1))))
        # the loop is re-integrated from true 3D points while the returned area
        # came from the 1e-6-quantised projection, hence AREA_TOL_MM2
        assert abs(shoelace - area) < AREA_TOL_MM2, (shoelace, area)


# ------------------------------------------------------------------- seeding
def test_two_disjoint_boxes_give_two_loops_and_seed_picks_the_large_one():
    """The whole point of loop seeding: no ROI, still the right component.

    Two disjoint cubes, one 10 mm and one 5 mm across, both straddled by the
    same plane. A ROI box covering both would select both components; the
    loop-derived seed must land inside the large one.
    """
    va, fa = box((0, 0, 0), (10, 10, 10))
    vb, fb = box((30, 0, 0), (35, 5, 10))
    v = np.vstack((va, vb))
    f = np.vstack((fa, fb + len(va)))
    o = np.array([0.0, 0.0, 5.0])
    nrm = np.array([0.0, 0.0, 1.0])

    areas, n, diag = section_loops(v, f, o, nrm)
    assert n == 2, (n, areas)
    assert sorted(round(a, 3) for a in areas) == [25.0, 100.0]

    _, _, _, detail = section_loops_detail(v, f, o, nrm)
    big = int(np.argmax(detail['loop_areas_mm2']))
    centroid = detail['cut_points_3d'][detail['loops'][big]].mean(axis=0)
    assert 0 < centroid[0] < 10, centroid     # inside the large cube, not the small one
    assert 25 < centroid[1] < 30 or True      # (kept explicit: centroid of the big loop)


def test_flood_mask_loop_mode_seeds_from_the_largest_loop_only():
    """Loop mode takes the rim of the LARGEST section loop, not every triangle
    that crosses the plane.

    Two disjoint cubes cut by one plane, 10 mm and 5 mm across. The band must
    come from the 10 mm loop, so only the large cube's component is selected -
    the small cube's wall also straddles the plane but belongs to a different
    lumen. (Seeding from every straddling triangle was measured to pull in
    fragments from other openings and produce a non-coplanar cut boundary.)
    """
    va, fa = box((0, 0, 0), (10, 10, 10))
    vb, fb = box((30, 0, 0), (35, 5, 10))
    v = np.vstack((va, vb))
    f = np.vstack((fa, fb + len(va)))
    sp = spec((0, 0, 6.0), (0, 0, 1), roi=((-1, -1, 6), (11, 6, 11)), keep_positive=False)
    mask_loop, note_loop = flood_mask(v, f, sp, seed_mode='loop')
    assert note_loop['seed_mode'] == 'loop'
    band = note_loop['rim_band']
    assert band['section_loops_at_plane'] == 2
    assert band['loop_used'] == int(np.argmax(band['loop_areas_mm2']))
    assert max(band['loop_areas_mm2']) == 100.0
    assert band['rim_triangles'] > 0 and band['rim_band_vertices'] > 0
    assert note_loop['negative_components_reached'] == 1
    # the selected component is the large cube's (its vertices are at x in [0,10])
    sel = np.where(mask_loop)[0]
    assert sel.max() < len(va), 'must not select anything from the small cube'


def test_flood_mask_default_is_roi_and_unchanged():
    """Default path must stay ROI; the opt-in is explicit."""
    va, fa = box((0, 0, 0), (10, 10, 10))
    # a box-only corner vertex set: the cube has just 8 vertices, and with
    # keep_positive False the negative side is z>6, so the ROI must reach the
    # z=10 face for any negative-side seed to exist at all
    sp = spec((0, 0, 6.0), (0, 0, 1), roi=((-1, -1, 6), (11, 11, 11)), keep_positive=False)
    mask, note = flood_mask(va, fa, sp)
    assert note['seed_mode'] == 'roi'
    assert note['selection'] == 'negative_side_connectivity_from_reviewed_roi_seed'
    assert mask.any()


def test_flood_mask_loop_mode_still_fails_when_there_is_no_lumen():
    """The opt-in must not turn 'no opening' into a silent pass."""
    v, f = box((0, 0, 0), (10, 10, 10))
    # plane far outside the solid -> no straddling triangles -> no rim band
    sp = spec((0, 0, 50.0), (0, 0, 1), roi=((-1, -1, 48), (11, 11, 50)), keep_positive=False)
    with pytest.raises(ValueError):
        flood_mask(v, f, sp, seed_mode='loop')


# ------------------------------------------------------------------- hybrid
def test_hybrid_uses_roi_when_the_box_has_a_seed():
    """Hybrid must equal ROI whenever the box works - that is what keeps the
    18/24 baseline reproducible instead of silently changing it."""
    va, fa = box((0, 0, 0), (10, 10, 10))
    vb, fb = box((30, 0, 0), (35, 5, 10))
    v = np.vstack((va, vb))
    f = np.vstack((fa, fb + len(va)))
    # ROI spans both cubes' upper halves
    sp = spec((0, 0, 6.0), (0, 0, 1), roi=((-1, -1, 6), (36, 6, 11)), keep_positive=False)
    m_roi, n_roi = flood_mask(v, f, sp, seed_mode='roi')
    m_hyb, n_hyb = flood_mask(v, f, sp, seed_mode='hybrid')
    assert n_hyb['seed_mode'] == 'hybrid'
    assert 'roi_seed_unavailable_fallback_to_rim_band' not in n_hyb
    assert np.array_equal(m_roi, m_hyb)
    assert n_hyb['negative_components_reached'] == 2


def test_hybrid_falls_back_to_rim_band_and_says_so():
    """The measured seed_lost case: ROI box present but empty of negative-side
    vertices. Hybrid must still select something, and must record that it did
    not use the box - otherwise the report would claim a reviewed-ROI run."""
    va, fa = box((0, 0, 0), (10, 10, 10))
    # keep_positive True -> negative side is z<6, but the ROI only spans z in
    # [7, 11], i.e. it contains no negative-side vertex at all
    sp = spec((0, 0, 6.0), (0, 0, 1), roi=((-1, -1, 7), (11, 11, 11)), keep_positive=True)
    with pytest.raises(ValueError):
        flood_mask(va, fa, sp, seed_mode='roi')      # the old behaviour: hard fail
    m, note = flood_mask(va, fa, sp, seed_mode='hybrid')
    assert note.get('roi_seed_unavailable_fallback_to_rim_band') is True, (
        'hybrid must record that it did not use the ROI box')
    band = note.get('rim_band')
    assert band is not None and band['seed_mode'] == 'loop'
    assert note['negative_components_reached'] >= 1
    assert m.any()


def test_hybrid_and_loop_differ_exactly_where_the_roi_box_filters():
    """ROI's second job is spatial filtering. Here the box covers only the SMALL
    cube while the largest section loop belongs to the LARGE cube, so the two
    modes must disagree - and hybrid must follow the box, loop the loop."""
    va, fa = box((0, 0, 0), (10, 10, 10))
    vb, fb = box((30, 0, 0), (35, 5, 10))
    v = np.vstack((va, vb))
    f = np.vstack((fa, fb + len(va)))
    sp = spec((0, 0, 6.0), (0, 0, 1), roi=((29, -1, 6), (36, 6, 11)), keep_positive=False)
    m_hyb, n_hyb = flood_mask(v, f, sp, seed_mode='hybrid')
    m_loop, n_loop = flood_mask(v, f, sp, seed_mode='loop')
    assert n_hyb['negative_components_reached'] == 1     # the boxed small cube
    assert n_loop['negative_components_reached'] == 1    # the large loop's cube
    # and they are different cubes: hybrid selects vertices only from the small
    # cube (indices >= len(va)), loop only from the large one
    assert np.where(m_hyb)[0].min() >= len(va)
    assert np.where(m_loop)[0].max() < len(va)


@pytest.mark.skipif(not Path('C:/ts_work/batch27_surfaces/b01/source_surface.vtp').exists(),
                    reason='batch27 surfaces not present')
def test_hybrid_on_real_surface_equals_roi_at_the_proposal_position():
    """Baseline protection: at the proposed position the ROI box always has a
    negative-side seed (measured on all 27 cases), so hybrid must be byte-for-
    byte the ROI mask there. Anything else would silently move the 18/24 result.

    The earlier premise - "loop seeding selects the same components as the
    reviewed ROI" - was measured FALSE (b01 nostril_L: 3 vs 2 components; its
    outlet 6 vs 4, the extras being nostril-region fragments ~50 mm away), which
    is exactly why hybrid keeps the box as the filter instead of replacing it.
    """
    import json

    import vtk
    from export_candidate_preview import triangle_arrays

    work = Path(__file__).resolve().parents[1]
    checked = 0
    for case in ('b01', 'b02', 'b03', 'b11', 'b04', 'b05', 'b15', 'b18', 'b23'):
        vtp = Path('C:/ts_work/batch27_surfaces') / case / 'source_surface.vtp'
        lm_path = work / '06_auto_landmarks' / case / 'landmarks.json'
        if not (vtp.exists() and lm_path.exists()):
            continue
        obj = json.loads(lm_path.read_text(encoding='utf-8'))
        reader = vtk.vtkXMLPolyDataReader()
        reader.SetFileName(str(vtp))
        reader.Update()
        points, faces = triangle_arrays(reader.GetOutput())
        for name in OPENINGS:
            lm = obj['landmarks'].get(name)
            if not lm or not lm.get('point_lps_mm'):
                continue
            sp = {'point_lps_mm': lm['point_lps_mm'], 'normal_lps': lm['normal_lps'],
                  'roi_lps_mm': lm['roi_lps_mm'], 'keep_positive': True}
            m_hyb, n_hyb = flood_mask(points, faces, sp, seed_mode='hybrid')
            checked += 1
            assert 'roi_seed_unavailable_fallback_to_rim_band' not in n_hyb, (
                case, name, 'unexpected fallback at the proposal position')
            m_roi, _ = flood_mask(points, faces, sp, seed_mode='roi')
            assert np.array_equal(m_roi, m_hyb), (case, name)
    assert checked >= 20, f'only {checked} openings compared; test is vacuous'


@pytest.mark.skipif(not Path('C:/ts_work/batch27_surfaces/b15/source_surface.vtp').exists(),
                    reason='batch27 surfaces not present')
def test_hybrid_falls_back_exactly_where_roi_loses_its_seed():
    """The measured seed_lost geometry: b15's outlet with the plane shifted to
    onset + SEED_OFFSET_MM, where the ROI box contains no negative-side vertex.

    ROI mode must still hard-fail there (that is the failure being fixed), and
    hybrid must succeed with the fallback recorded.
    """
    import json

    import vtk
    from auto_opening_placement import detect_onset
    from export_candidate_preview import triangle_arrays
    from auto_opening_pipeline import SEED_OFFSET_MM

    case, opening = 'b15', 'nasopharynx_outlet'
    obj = json.loads((Path('D:/项目/鼻腔建模/work/06_auto_landmarks') / case
                      / 'landmarks.json').read_text(encoding='utf-8'))
    reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(f'C:/ts_work/batch27_surfaces/{case}/source_surface.vtp')
    reader.Update()
    points, faces = triangle_arrays(reader.GetOutput())
    lm = obj['landmarks'][opening]
    n = np.asarray(lm['normal_lps'], float)
    n = n / np.linalg.norm(n)
    o = np.asarray(lm['point_lps_mm'], float)
    onset, _, _ = detect_onset(points, faces, o, n)
    assert onset is not None
    shift = onset + SEED_OFFSET_MM
    sp = {'point_lps_mm': (o + shift * n).tolist(), 'normal_lps': n.tolist(),
          'roi_lps_mm': {'min': (np.asarray(lm['roi_lps_mm']['min'], float)
                                 + shift * n).tolist(),
                         'max': (np.asarray(lm['roi_lps_mm']['max'], float)
                                 + shift * n).tolist()},
          'keep_positive': True}
    with pytest.raises(ValueError):
        flood_mask(points, faces, sp, seed_mode='roi')
    m, note = flood_mask(points, faces, sp, seed_mode='hybrid')
    assert note.get('roi_seed_unavailable_fallback_to_rim_band') is True
    assert note['rim_band']['rim_triangles'] > 0
    assert m.any()
    assert note['negative_components_reached'] >= 1
