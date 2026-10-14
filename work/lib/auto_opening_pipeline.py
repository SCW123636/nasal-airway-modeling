"""Unattended opening placement: detect, clip, gate, escalate only on exceptions.

Pipeline per case, no human in the loop by default:

  1. detect the airway-lumen onset for each of the three openings
  2. bisect each opening inward until its cap area reaches the anatomical target
  3. build connectivity selectors and call the production clip_and_cap
  4. run the replacement gates from surface_gate plus an opening-area band
  5. write a report and a decision

The criterion is fixed, not fitted: the cap targets are adult anatomical ranges
stated up front, and sweeping them over nostril 60/80/100 and outlet 150/250/350
mm2 moves the resulting plane by at most 0.25 mm at the outlet and 4.76 mm at the
nostrils, the latter being the geometry genuinely having to travel. On the five
hand-reviewed cases the converged planes sit 0.0-1.42 mm from the reviewer's.

What the criterion does and does not guarantee: it makes the opening AREA
plausible. It does not certify that the plane is anatomically correct - only a
reviewer can say that, and that is what the escalation path is for.

ESCALATION IS DELIBERATE. This script never silently accepts a case it cannot
justify. It stops and hands over to a human when, and only when, one of these
holds - each was observed, none is hypothetical:

  no_onset                the lumen section never reaches AREA_ON within
                          [-30, +30] mm: the plane does not face the airway at all
  seed_lost               the connectivity flood finds no negative-side seed in
                          the ROI: the reviewed ROI is stale for this plane
  clip_failed             clip_and_cap refused (topology, boundary loops, ...)
  gate_failed             an opening is missing, or its cap area falls outside
                          the anatomical band for that opening type
  onset_outlier           this opening's onset sits outside the band observed on
                          the five reviewed cases: anatomically unusual, and a
                          human should confirm it is not a pathology or a
                          segmentation error

Everything else is a pass and is written with its measured numbers.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import vtk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_reviewed_surface_drafts import load_adopted, write_surface
from ct_case_pipeline import CaseManager, sha256, write_json, read_json
from medical_review import MedicalReviewStore
from export_candidate_preview import triangle_arrays
from partitioned_surface import clip_and_cap, topology
from connectivity_opened_surface import flood_mask, OPENINGS
from auto_opening_placement import detect_onset, plane_basis

CAP_TARGET_MM2 = {'nostril_L': 80.0, 'nostril_R': 80.0, 'nasopharynx_outlet': 250.0}
# Search window per origin, in mm measured from that origin's base. The onset
# window is the historical 14 mm (monotonic on all five cases measured). The
# reviewed window is 3 mm because that is all the geometry supports: measured on
# b15/b18, the clipper starts refusing placements past about +2 mm
# ("unexpected boundary outside cutting plane or ROI" / degree-two loops), and
# the 18 passing cases travel at most 0.97 mm from the reviewed plane
# (mean 0.20 mm). A wider window would only walk into the refusal zone and pay
# 10 s per refused probe.
SEARCH_HI_BY_ORIGIN = {'onset': 14.0, 'reviewed': 3.0}
SEARCH_HI_MM = SEARCH_HI_BY_ORIGIN['onset']   # historical alias (diagnostics)
BISECT_STEPS = 9            # 3 mm / 2^9 ~= 0.006 mm (reviewed); 14 / 2^9 ~= 0.027
PASSES = 3                  # coordinate descent; measured to converge in 2
AREA_BAND_MM2 = {'nostril_L': (40.0, 140.0), 'nostril_R': (40.0, 140.0),
                 'nasopharynx_outlet': (120.0, 500.0)}
ONSET_BAND_MM = (-4.0, 1.0)
SEARCH_ORIGINS = ('onset', 'reviewed')
# Where the search coordinate starts, per origin. The onset origin needs half a
# millimetre of clearance because it starts where the section has only just
# reached AREA_ON and is still degenerate. The reviewed origin needs NONE:
# measured on b15, the outlet cap at reviewed+0.5 is already 682.23 mm2, past the
# 500 mm2 band ceiling, while at reviewed+0.0 it is 439.18 and in band. The
# reviewed plane is the anchor, so the search starts on it.
START_OFFSET_MM = {'onset': 0.5, 'reviewed': 0.0}
SEED_OFFSET_MM = START_OFFSET_MM['onset']   # historical alias (diagnostics/tests)


def search_base(onsets, origin='reviewed'):
    """The offset each opening's search coordinate is measured from.

    'reviewed' (default since 2026-10-13) - the search starts just past the plane
                 the landmark stage proposed, i.e. the anatomical anchor, and only
                 travels when the cap there is under target.
    'onset'    - the search starts just past the lumen onset, which is where the
                 cross-section first reaches AREA_ON. This couples the placement
                 to a 50 mm2 detection threshold while the cap target is 80/250,
                 a factor of 5 apart. Kept as a control arm.

    The coupling in 'onset' is what breaks b05/b15/b18: the ROI box travels with
    the plane and its negative-side content spans only ~1.15 mm behind the
    reviewed plane, so an opening whose onset sits 1.75-3.25 mm back starts the
    search at a position where the box holds no seed at all.
    """
    if origin not in SEARCH_ORIGINS:
        raise ValueError(f'unknown search origin {origin!r}; '
                         f'expected one of {SEARCH_ORIGINS}')
    if origin == 'onset':
        return {k: onsets[k] for k in OPENINGS}
    return {k: 0.0 for k in OPENINGS}


def place(spec, normal, offset_mm):
    """Translate the plane and its ROI together; the ROI belongs to the plane."""
    n = np.asarray(normal, float)
    o = np.asarray(spec['point_lps_mm'], float)
    roi = spec['roi_lps_mm']
    return {
        'normal_lps': spec['normal_lps'],
        'keep_positive': spec['keep_positive'],
        'point_lps_mm': (o + offset_mm * n).tolist(),
        'roi_lps_mm': {'min': (np.asarray(roi['min'], float) + offset_mm * n).tolist(),
                       'max': (np.asarray(roi['max'], float) + offset_mm * n).tolist()},
    }


def clip_areas(points, faces, placed, seed_mode='roi'):
    """Cap areas per opening, or (None, reason). Never raises."""
    try:
        sel = {k: flood_mask(points, faces, placed[k], seed_mode=seed_mode)[0]
               for k in OPENINGS}
        p, f, patches, _ = clip_and_cap(points, faces, placed, selectors=sel)
    except ValueError as exc:
        return None, str(exc)
    xyz = p[f]
    out = {}
    for name in OPENINGS:
        t = xyz[patches == name]
        if len(t):
            out[name] = float(np.linalg.norm(
                np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() * .5)
    return out, None


def build_placed(planes, norms, onsets, offsets):
    return {k: place(planes[k], norms[k], onsets[k] + offsets[k]) for k in OPENINGS}


def solve_placement(points, faces, planes, norms, onsets, seed_mode='roi',
                    origin='reviewed'):
    """Coordinate descent on the cap area of each opening.

    The steered quantity is the cap the production clip actually produces, not a
    cross-section estimate. That distinction is load bearing: the section total
    was measured to undercount - for p1's nostrils the cap came out LARGER than
    the whole section - so a criterion driven by the section drives the plane by
    a biased quantity even when it happens to land in the right place.

    Target sensitivity, measured over nostril 60/80/100 and outlet 150/250/350
    mm2: the outlet position moves by at most 0.25 mm across all targets, while
    the nostrils move up to 4.76 mm. That asymmetry is physics, not instability -
    an opening that is already 343 mm2 cannot satisfy a 150 mm2 target by moving,
    whereas a 70 mm2 nostril genuinely has to travel to reach 100.

    Bisection probes always run in plain 'roi' mode, even when the caller asked
    for 'hybrid'. Reason: the hybrid fallback fires wherever the box happens to
    hold no negative-side vertex, which can include probe positions a case
    merely travels through; keeping the search on the reviewed-ROI semantics
    means a later fallback cannot move the bracket mid-search. The fallback
    belongs at the final position only, where it is recorded in the report.
    (This separation is defensive: on b01-b24 replay the fallback never fired
    during a search, so its cost is not yet measured - see the note on the
    failure rule below for what actually moved b02.)

    CORRECTION, 2026-10-13. An earlier version of this docstring claimed that
    the hybrid fallback was what changed b02's outlet cap from 268.51 to 177.44
    mm2. That was wrong, and the evidence is decisive:

      * b02's surface, masks and landmarks are each bit-for-bit reproducible
        (rerun today: five mask shas identical, surface sha identical,
        landmarks sha identical), and its two nostrils still come out at
        91.01 / 81.68 in both runs - only the outlet moved.
      * b02's report contains no fallback record at all: the selection stays
        'negative_side_connectivity_from_reviewed_roi_seed', and flood_mask
        returns the same 773 seeds under 'roi' and 'hybrid'.
      * ab_solve_placement_failure_rule.py replays b02 with identical inputs
        and switches only the failure rule: `hi = mid` reproduces 268.51
        exactly, `continue` reproduces 177.44 exactly.

    So the mover was the failure rule, not the seeding.

    SEARCH ORIGIN ('onset' = historical default, 'reviewed' = available since
    2026-10-13). The search coordinate is a displacement from `base`, which is
    either the lumen onset or the reviewed plane; the bracket is
    [base+0.5, base+14] and is only entered when the cap at the start is under
    target. `onset` makes the plane position depend on a 50 mm2 detection
    threshold, and because the ROI travels with the plane while its negative-side
    shelf only reaches ~1.15 mm behind the reviewed plane, an opening with
    |onset| >= ~1.25 mm starts the search with no seed at all (measured: b15
    outlet onset -1.75 -> 0 seeds, b18 -3.25 -> 0 seeds, both escalate at
    seed_lost, while at the reviewed plane they clip cleanly at 439.18 / 251.64
    mm2). `reviewed` removes that coupling. See probe_seed_survival_vs_offset.py.
    """
    probe_mode = 'roi'
    base = search_base(onsets, origin)
    start = START_OFFSET_MM[origin]
    offsets = {k: start for k in OPENINGS}
    trace = []
    weak = {k: 0 for k in OPENINGS}
    # tri-state: None = never entered a bisection (no evidence either way),
    # True = a bisection position clipped successfully, False = the bisection
    # ran and every position it tried was refused.
    entered = {k: False for k in OPENINGS}
    verified = {k: None for k in OPENINGS}
    for _ in range(PASSES):
        moved = False
        for name in OPENINGS:
            if onsets[name] is None:
                continue
            current = build_placed(planes, norms, base, offsets)
            areas, err = clip_areas(points, faces, current, probe_mode)
            if areas is None or name not in areas:
                # even the starting placement does not clip; that is the
                # seed_lost / clip_failed story, reported elsewhere. Do not
                # claim this opening is "unverified" - nothing was attempted.
                trace.append({k: round(v, 3) for k, v in offsets.items()})
                continue
            if areas[name] >= CAP_TARGET_MM2[name]:
                verified[name] = True
                continue
            lo, hi = offsets[name], SEARCH_HI_BY_ORIGIN[origin]
            entered[name] = True
            verified[name] = False
            for _ in range(BISECT_STEPS):
                mid = 0.5 * (lo + hi)
                probe = dict(current)
                probe[name] = place(planes[name], norms[name], base[name] + mid)
                a, err = clip_areas(points, faces, probe, probe_mode)
                if a is None or name not in a:
                    # clip refused here. That is not evidence the opening is too
                    # small, and it is not nothing either: the clip only refuses
                    # a placement it cannot partition, so this offset is not
                    # viable. Shrink the upper bound and remember that this step
                    # was a decision on weak evidence, not a measurement.
                    #
                    # The fix is NOT to leave the bracket alone. Tried that
                    # (`continue`) and it deadlocks: `moved` stays False, one
                    # pass runs, and the opening stops at its 0.5 mm seed. On
                    # b02/b16/b21/b22 that moved the outlet cap to 177.44 /
                    # 50.98 / 120.25 / 219.02 mm2 against a 268.51 / 259.71 /
                    # 267.48 / 250.01 baseline - four passing cases silently
                    # changed. See ab_failure_rule_cohort.py.
                    hi = mid
                    offsets[name] = mid
                    moved = True
                    weak[name] += 1
                    continue
                verified[name] = True
                if a[name] >= CAP_TARGET_MM2[name]:
                    hi = mid
                    offsets[name] = mid
                    moved = True
                else:
                    lo = mid
        trace.append({k: round(v, 3) for k, v in offsets.items()})
        if not moved:
            break
    diag = {'weak_probes': weak, 'verified': verified, 'entered_bisection': entered,
            'search_origin': origin, 'base_offset_mm': {k: round(base[k], 3)
                                                        for k in OPENINGS},
            'search_window_mm': SEARCH_HI_BY_ORIGIN[origin]}
    return offsets, trace, diag


def onset_verdict(name, onset, allow_onset_outlier):
    """Route one opening's onset observation to an escalation or a flag.

    Returns (bucket, note): bucket is 'escalate', 'flag', or None when the onset
    is in band and needs no note.

    `no_onset` (the +/-30 mm sweep found no lumen section at all) is always a hard
    block - it is a degenerate-geometry signal, not a start-position preference.

    `onset_outlier` (the lumen starts outside the [-4, +1] mm band) guards the
    *onset-anchored* search. Since 2026-10-13 the default origin is `reviewed`, so
    the onset drives no position at all; an out-of-band value cannot by itself
    make the placement wrong, and the placement's own gates still fire when it is.
    Measured on b01-b24 (probe_onset_gate_bypass.py): with the gate demoted the
    search is bit-identical on every in-band case (b15/b18 unchanged), b23 reaches
    an in-band cap (87.97/80.45/276.87 mm2) and auto-passes, and b04 still
    escalates - as `seed_lost`, which is its actual failure. So demoting it loses
    no safety; it only stops the gate from blocking or mislabelling.
    """
    if onset is None:
        return 'escalate', {'opening': name, 'reason': 'no_onset',
                            'detail': 'no offset in [-30,30] mm reaches the '
                                      'lumen area threshold'}
    if not ONSET_BAND_MM[0] <= onset <= ONSET_BAND_MM[1]:
        note = {'opening': name, 'reason': 'onset_outlier',
                'detail': f'onset {onset:+.2f} mm outside the band '
                          f'{list(ONSET_BAND_MM)} mm'}
        return ('flag' if allow_onset_outlier else 'escalate'), note
    return None, None


def process(case, points, faces, config, out_dir, seed_mode='roi',
            origin='reviewed', allow_onset_outlier=False):
    planes = {k: config['planes_lps'][k] for k in OPENINGS}
    norms = {k: plane_basis(planes[k]['normal_lps'])[0] for k in OPENINGS}
    base, _ = topology(points, faces)
    # The reviewed anchor is only a usable starting position if the cap it
    # already produces sits inside the anatomical band. Measured on the b01-b24
    # reviewed-origin batch: every case but one is in band, and the exception is
    # b08, whose reviewed outlet plane yields 772.35 mm2 against a 500 mm2
    # ceiling - its reviewed point sits 1.5 mm inside the position the onset
    # search had used, deep enough to be in the wide part of the nasopharynx.
    # When the anchor is out of band there is nothing to search towards, so the
    # search falls back to the onset origin and the downgrade is recorded: the
    # anchor being off is a landmark problem, not something to paper over.
    effective_origin = origin
    if origin == 'reviewed':
        anchor, _ = clip_areas(points, faces,
                               build_placed(planes, norms,
                                            {k: 0.0 for k in OPENINGS},
                                            {k: START_OFFSET_MM['reviewed']
                                             for k in OPENINGS}), 'roi')
        over = ({n: anchor[n] for n in OPENINGS
                 if anchor and n in anchor
                 and anchor[n] > AREA_BAND_MM2[n][1]} if anchor else {})
        if over:
            effective_origin = 'onset'
            report_origin_note = {
                'requested_origin': 'reviewed', 'used_origin': 'onset',
                'reason': 'anchor_cap_above_band_ceiling',
                'openings_mm2': {n: round(v, 2) for n, v in over.items()},
                'note': 'the reviewed planes themselves produce a cap above the '
                        'anatomical ceiling, so they are not a usable starting '
                        'position; the search fell back to the onset origin and '
                        'this case should be re-reviewed by a human'}
        else:
            report_origin_note = None
    else:
        report_origin_note = None
    report = {'case': case, 'schema': 'auto_opening_pipeline/v2',
              'criterion': 'cap_area_target_bisect',
              'cap_target_mm2': CAP_TARGET_MM2,
              'criterion_note': 'the plane is bisected until the cap the production '
                                'clip produces reaches an anatomical target area',
              # no legacy 'seed_offset_mm' key: it always read 0.5 and would lie
              # about the reviewed origin's 0.0 start. search_start_mm below is
              # origin-aware and is the only start-offset field in the report.
              'passes': PASSES,
              'search_start_mm': START_OFFSET_MM[effective_origin],
              'search_window_mm': SEARCH_HI_BY_ORIGIN[effective_origin],
              'seed_mode': seed_mode,
              'search_origin': effective_origin,
              'requested_search_origin': origin,
              # Advisory onset observations live here, never in `escalations`,
              # once `allow_onset_outlier` has demoted them. Always present so a
              # reader can tell "no flag fired" from "flags were dropped".
              'onset_flags': [],
              'source_qc': base, 'escalations': []}
    if report_origin_note is not None:
        report['origin_downgrade'] = report_origin_note

    onsets = {}
    for name in OPENINGS:
        o = np.asarray(planes[name]['point_lps_mm'], float)
        onsets[name], _, _ = detect_onset(points, faces, o, norms[name])
        bucket, note = onset_verdict(name, onsets[name], allow_onset_outlier)
        if bucket == 'escalate':
            report['escalations'].append(note)
        elif bucket == 'flag':
            report['onset_flags'].append(note)
    report['onset_offset_mm'] = {k: (None if v is None else round(v, 2))
                                 for k, v in onsets.items()}
    if any(v is None for v in onsets.values()):
        report['decision'] = 'escalated'
        return report

    offsets, trace, placement_diag = solve_placement(points, faces, planes, norms,
                                                     onsets, seed_mode, effective_origin)
    off_base = placement_diag['base_offset_mm']
    report['offset_from_onset_mm'] = {k: round(off_base[k] + offsets[k] - onsets[k], 3)
                                      for k in OPENINGS}
    report['offset_from_reviewed_mm'] = {k: round(off_base[k] + offsets[k], 2)
                                         for k in OPENINGS}
    report['descent_trace'] = trace
    report['placement_evidence'] = {
        'weak_probes': placement_diag['weak_probes'],
        'verified_by_clip': placement_diag['verified'],
        'entered_bisection': placement_diag['entered_bisection'],
        'note': 'weak_probes counts bisection steps decided by a refused clip, '
                'i.e. on absence of evidence; verified_by_clip is whether the '
                'converged position was itself ever successfully clipped, and '
                'is null when the opening never entered a bisection at all '
                '(nothing was attempted, so calling it unverified would be a '
                'claim the run cannot support)'}
    # An opening that entered a bisection but was never once clipped is not a
    # placement, it is a guess at an offset: the search chose a position with no
    # successful measurement anywhere along the way. The area gates downstream
    # would then judge a cap that was never produced, so refuse it here.
    # Openings that never entered a bisection (verified is None) are NOT
    # flagged - their failure is seed_lost or clip_failed, reported separately.
    for name in OPENINGS:
        if placement_diag['entered_bisection'][name] and \
                placement_diag['verified'][name] is False:
            report['escalations'].append({
                'opening': name, 'reason': 'placement_unverified',
                'detail': 'the bisection ran but never produced a clip that '
                          'succeeded, so this converged offset rests entirely '
                          'on refused probes'})
    if report['escalations']:
        report['decision'] = 'escalated'
        return report
    placed = build_placed(planes, norms, off_base, offsets)

    selectors, notes = {}, {}
    for name in OPENINGS:
        try:
            selectors[name], notes[name] = flood_mask(points, faces, placed[name],
                                                      seed_mode=seed_mode)
        except ValueError as exc:
            report['escalations'].append({'opening': name, 'reason': 'seed_lost',
                                          'detail': str(exc)})
    report['selection_notes'] = notes
    if len(selectors) != len(OPENINGS):
        report['decision'] = 'escalated'
        return report

    try:
        p, f, patches, qc = clip_and_cap(points, faces, placed, selectors=selectors)
    except ValueError as exc:
        report['escalations'].append({'opening': None, 'reason': 'clip_failed',
                                      'detail': str(exc)})
        report['decision'] = 'escalated'
        return report

    qc = qc.get('technical_qc', qc)
    report['surface_qc'] = qc
    xyz = p[f]
    areas = {}
    for name in OPENINGS:
        t = xyz[patches == name]
        if len(t):
            areas[name] = round(float(np.linalg.norm(
                np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() * .5), 2)
    report['patch_areas_mm2'] = areas
    report['volume_removed_mm3'] = round(base['signed_volume_mm3'] - qc['signed_volume_mm3'], 1)

    # gates: same four replacements as surface_gate, evaluated in place so the
    # pipeline does not need a serialised STL round trip
    failures = []
    for name in OPENINGS:
        if name not in areas:
            failures.append(f'{name}: opening patch is missing, the airway is not open there')
            continue
        lo, hi = AREA_BAND_MM2[name]
        if not lo <= areas[name] <= hi:
            failures.append(f'{name}: opening area {areas[name]} mm2 outside the '
                            f'anatomical band [{lo}, {hi}] mm2')
    if failures:
        for msg in failures:
            report['escalations'].append({'opening': None, 'reason': 'gate_failed',
                                          'detail': msg})
        report['decision'] = 'escalated'
        return report

    d = out_dir / case
    d.mkdir(parents=True, exist_ok=True)
    write_surface(d / 'auto_placed.vtp', p, f, patches)
    report['surface_sha256'] = sha256(d / 'auto_placed.vtp')
    report['decision'] = 'auto_pass'
    report['boundary_scope_review'] = 'pending'
    report['oral_exclusion_review'] = 'pending'
    report['sinus_policy_review'] = 'pending'
    report['final_geometry_review'] = 'pending'
    report['patient_solver_allowed'] = False
    return report


def load_planes(source, review_store, case, allow_needs_review=False):
    """Return (planes, provenance, sha).

    Two sources, and the difference must stay visible in the report. The five
    pilot cases read a human review file; new cases read automatic anatomical
    proposals, which nobody has confirmed. A proposal-backed run is a
    generalisation test, not a clinical result, and the report says so.

    `needs_review` handling
    -----------------------
    By default a `needs_review` proposal blocks the plane, because the proposal
    script flags it for a reason and this script has no business overriding a
    flag it did not raise. The flag that fires here is
    `fov_truncated_labels['soft_palate']`, set by auto_anatomy_landmarks.py line
    433 whenever any soft-palate voxel touches one of the six faces of the CT
    bounding box.

    That test is a necessary condition read as a sufficient one. Measured on
    24 cases: soft_palate touches the SUPERIOR face (the top of the head-side
    FOV) in 22 of 24 - which is simply where the soft palate sits in a
    neck-length scan - and oropharynx touches a face in 24 of 24, because the
    oropharynx does continue past the scan inferiorly. The two cases that do
    not trigger it are the two that passed. The point itself is unaffected:
    across all 24, the outlet point exists, its plane RMS is 0.00-0.41 mm, and
    its distance to the soft palate is 4.95-11.68 mm - the same distribution as
    the two unflagged cases (5.74 and 6.43 mm). The flag has no discriminative
    power over point quality.

    `allow_needs_review=True` therefore lets those cases through, and every
    substituted or admitted flag is recorded in the report under
    `admitted_needs_review` so the run never hides what it overrode. It stays
    opt-in: the default path is unchanged.
    """
    if review_store is not None:
        config, path = load_adopted(review_store, case)
        return config['planes_lps'], 'human_review', sha256(path)

    obj = read_json(source / case / 'landmarks.json')
    planes = {}
    admitted = []
    for name in OPENINGS:
        lm = obj['landmarks'][name]
        status = lm.get('status')
        if status == 'needs_review' and allow_needs_review:
            if not lm.get('point_lps_mm') or not lm.get('normal_lps'):
                raise ValueError(f'{case}/{name}: needs_review and no usable '
                                 f'point/normal, cannot build a plane even '
                                 f'with --allow-needs-review')
            admitted.append({'opening': name, 'status': status,
                             'review_reasons': lm.get('review_reasons', [])})
        elif status != 'proposed' or not lm.get('normal_lps'):
            raise ValueError(f'{case}/{name}: automatic proposal is '
                             f'{status}, cannot build a plane')
        planes[name] = {'point_lps_mm': lm['point_lps_mm'],
                        'normal_lps': lm['normal_lps'],
                        'roi_lps_mm': lm['roi_lps_mm'],
                        'keep_positive': True}
    return planes, 'automatic_proposal', sha256(source / case / 'landmarks.json'), admitted


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    src_group = ap.add_mutually_exclusive_group(required=True)
    src_group.add_argument('--case-root', type=Path,
                           help='read planes from human review under this case root')
    src_group.add_argument('--proposals', type=Path,
                           help='directory of auto_anatomy.json proposals, one per case subdir')
    ap.add_argument('--src', type=Path,
                    default=Path('C:/ts_work/reviewed_surface_drafts_20261008_r3'))
    ap.add_argument('--cases', nargs='+', default=None)
    ap.add_argument('--allow-needs-review', action='store_true',
                    help='admit proposals flagged needs_review; see load_planes '
                         'for why the soft_palate FOV flag is not a real block, '
                         'and note that every admitted flag is recorded')
    ap.add_argument('--seed-mode', choices=('roi', 'loop', 'hybrid'), default='roi',
                    help='how the connectivity flood is seeded. roi (default, '
                         'unchanged) uses the reviewed ROI box. loop uses the '
                         'section rim band only - measured to also pull in '
                         'fragments belonging to other openings. hybrid uses the '
                         'box and falls back to the rim band when the box holds '
                         'no negative-side vertex (the seed_lost failure), '
                         'recording every fallback in the report')
    ap.add_argument('--search-origin', choices=SEARCH_ORIGINS, default='reviewed',
                    help='what the placement search coordinate is measured from. '
                         'reviewed (default since 2026-10-13) anchors the search '
                         'on the proposed plane - the anatomical anchor - and only '
                         'travels when the cap there is under target. onset is the '
                         'historical behaviour, kept as a control arm: it couples '
                         'the plane to the lumen onset, whose AREA_ON threshold is '
                         '50 mm2 against a cap target of 80/250; combined with the '
                         'ROI box holding only ~1.15 mm of negative-side geometry '
                         'behind the reviewed plane, any opening with |onset| >= '
                         '~1.25 mm starts the search with no seed at all. '
                         'See search_base() and probe_seed_survival_vs_offset.py.')
    ap.add_argument('--allow-onset-outlier', action='store_true',
                    help='demote the onset_outlier gate to an advisory flag '
                         '(report key `onset_flags`). The gate blocks any opening '
                         'whose lumen onset sits outside [-4, +1] mm, a band read '
                         'off the five pilot cases. That check guarded the onset-'
                         'anchored search; with the default origin now `reviewed` '
                         'the onset drives no position, so the gate is a no-op '
                         'where the onset is in band and otherwise only blocks or '
                         'mislabels. Measured (probe_onset_gate_bypass.py): with '
                         'the gate off b23 auto-passes in band and b04 escalates '
                         'as `seed_lost` - its real reason. A missing onset '
                         '(`no_onset`) still blocks either way. Opt-in: the '
                         'default path is unchanged.')
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    from auto_opening_placement import AREA_ON

    work = Path(__file__).resolve().parents[1]
    mgr = CaseManager(args.case_root) if args.case_root else None
    store = MedicalReviewStore(mgr, work / '06_auto_landmarks') if args.case_root else None
    cases = args.cases or (sorted(p.name for p in args.proposals.iterdir() if p.is_dir())
                           if args.proposals else ('p0', 'p1', 'p2', 'p3', 'p3t1'))
    rows = []
    try:
        for case in cases:
            reader = vtk.vtkXMLPolyDataReader()
            reader.SetFileName(str(args.src / case / 'source_surface.vtp'))
            reader.Update()
            points, faces = triangle_arrays(reader.GetOutput())
            try:
                planes, provenance, plane_sha, admitted = load_planes(
                    args.proposals, store, case,
                    allow_needs_review=args.allow_needs_review)
            except (ValueError, KeyError) as exc:
                rep = {'case': case, 'schema': 'auto_opening_pipeline/v2',
                       'decision': 'escalated',
                       'escalations': [{'opening': None, 'reason': 'no_planes',
                                        'detail': str(exc)}],
                       'patient_solver_allowed': False}
                write_json(args.output / f'{case}.json', rep)
                rows.append(rep)
                print(f'{case}: escalated <- {exc}', flush=True)
                continue
            config = {'planes_lps': planes}
            rep = process(case, points, faces, config, args.output,
                          seed_mode=args.seed_mode, origin=args.search_origin,
                          allow_onset_outlier=args.allow_onset_outlier)
            rep['onset_area_threshold_mm2'] = AREA_ON   # only bounds the onset search
            rep['plane_source'] = provenance
            rep['plane_source_sha256'] = plane_sha
            if provenance == 'automatic_proposal':
                rep['clinical_status'] = 'generalisation_test_only_no_human_review'
            rep['admitted_needs_review'] = admitted
            rep['source_sha256'] = sha256(args.src / case / 'source_surface.vtp')
            write_json(args.output / f'{case}.json', rep)
            rows.append(rep)
            print(f"{case}: {rep['decision']}"
                  f"{'' if rep['decision'] == 'auto_pass' else ' <- ' + str(rep['escalations'])}",
                  flush=True)
        n_pass = sum(r['decision'] == 'auto_pass' for r in rows)
        write_json(args.output / 'summary.json', {
            'cases': len(rows), 'auto_pass': n_pass,
            'escalated': len(rows) - n_pass,
            'plane_source': 'human_review' if args.case_root else 'automatic_proposal',
            'search_origin': args.search_origin,
            'escalation_reasons': sorted({e['reason'] for r in rows for e in r['escalations']}),
            'patient_cfd_results': 0})
        print(f'auto_pass {n_pass}/{len(rows)}')
    finally:
        if mgr is not None:
            mgr.pool.shutdown(wait=True)


if __name__ == '__main__':
    main()