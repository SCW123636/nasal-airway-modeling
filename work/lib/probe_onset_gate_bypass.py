"""Does the `onset_outlier` gate protect against anything real?

Read-only diagnostic. For each case it runs the production `process()` twice on
the exact same inputs:

  arm A  - stock pipeline          (ONSET_BAND_MM as shipped)
  arm B  - onset gate disabled     (ONSET_BAND_MM widened to (-30, +30) mm)

If arm B auto-passes, the gate is the *only* thing standing between the case and
a placed opening; then the question becomes whether the opening arm B produces
is anatomically plausible (band check on all three openings). If arm B still
fails, the gate is not what blocks it and the escalate reason is real.

Nothing is written outside the scratch directory.
"""
import sys
from pathlib import Path

import numpy as np
import vtk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import auto_opening_pipeline as A
from export_candidate_preview import triangle_arrays

ROOT = HERE.parents[1]
SURFACE_ROOT = Path('C:/ts_work/batch27_surfaces')
PROPOSALS = ROOT / 'work' / '06_auto_landmarks'
SCRATCH = ROOT / '.tools' / 'probe_onset_gate'


def load(case):
    reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(str(SURFACE_ROOT / case / 'source_surface.vtp'))
    reader.Update()
    points, faces = triangle_arrays(reader.GetOutput())
    planes, prov, sha, admitted = A.load_planes(PROPOSALS, None, case,
                                                allow_needs_review=True)
    return points, faces, {'planes_lps': planes}, prov, sha


def run(case):
    points, faces, config, prov, sha = load(case)
    rows = {}
    for arm, band in (('A_stock', None), ('B_gate_off', (-30.0, 30.0))):
        original = A.ONSET_BAND_MM
        if band is not None:
            A.ONSET_BAND_MM = band
        try:
            out = SCRATCH / arm
            out.mkdir(parents=True, exist_ok=True)
            rep = A.process(case, points, faces, config, out,
                            seed_mode='roi', origin='reviewed')
        finally:
            A.ONSET_BAND_MM = original
        rows[arm] = {
            'decision': rep.get('decision'),
            'escalations': [(e.get('opening'), e.get('reason')) for e in
                            (rep.get('escalations') or [])],
            'areas_mm2': rep.get('patch_areas_mm2'),
            'offset_from_onset_mm': rep.get('offset_from_onset_mm'),
            'placement_evidence': (rep.get('placement_evidence') or {}).get('verified'),
        }
    return rows


def band_flags(areas):
    if not areas:
        return ['<no areas>']
    bad = []
    for name, (lo, hi) in A.AREA_BAND_MM2.items():
        a = areas.get(name)
        if a is None or not lo <= a <= hi:
            bad.append(f'{name}={a}')
    return bad or ['all in band']


def main():
    cases = sys.argv[1:] or ['b04', 'b23', 'b15', 'b18']
    for case in cases:
        try:
            rows = run(case)
        except (ValueError, KeyError) as exc:
            print(f'{case}: cannot build planes -> {exc}')
            continue
        print(f'===== {case}')
        for arm in ('A_stock', 'B_gate_off'):
            r = rows[arm]
            print(f'  {arm:11s} decision={r["decision"]:9s} '
                  f'escalations={r["escalations"]}')
            if r['areas_mm2']:
                print(f'              areas={r["areas_mm2"]} -> {band_flags(r["areas_mm2"])}')
                print(f'              offset_from_onset={r["offset_from_onset_mm"]}')


if __name__ == '__main__':
    main()
