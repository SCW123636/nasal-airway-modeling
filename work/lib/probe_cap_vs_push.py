"""Cap area and cost as the plane travels away from the proposed position.

Read-only. Prints, per case/opening, the cap the production clip produces at a
set of pushes along the plane normal, with the wall time of each clip so a
pathological position is visible instead of looking like a hang.

Usage: probe_cap_vs_push.py [case ...]
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import vtk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
import auto_opening_pipeline as A
from auto_opening_placement import detect_onset, plane_basis
from export_candidate_preview import triangle_arrays

SURF = Path('C:/ts_work/batch27_surfaces')
LM = ROOT / 'work' / '06_auto_landmarks'
PUSHES = (0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 7.25)


def main():
    cases = sys.argv[1:] or ['b15', 'b18', 'b05', 'b02']
    for case in cases:
        r = vtk.vtkXMLPolyDataReader()
        r.SetFileName(str(SURF / case / 'source_surface.vtp'))
        r.Update()
        points, faces = triangle_arrays(r.GetOutput())
        o = json.loads((LM / case / 'landmarks.json').read_text(encoding='utf-8'))
        planes = {n: {'point_lps_mm': o['landmarks'][n]['point_lps_mm'],
                      'normal_lps': o['landmarks'][n]['normal_lps'],
                      'roi_lps_mm': o['landmarks'][n]['roi_lps_mm'],
                      'keep_positive': True} for n in A.OPENINGS}
        norms = {k: plane_basis(planes[k]['normal_lps'])[0] for k in A.OPENINGS}
        onsets = {}
        for n in A.OPENINGS:
            p = np.asarray(planes[n]['point_lps_mm'], float)
            onsets[n], _, _ = detect_onset(points, faces, p, norms[n])
        print(f'=== {case}  n_tri={len(faces)}  onsets='
              f'{ {k: (None if v is None else round(v, 2)) for k, v in onsets.items()} }',
              flush=True)
        for push in PUSHES:
            placed = {n: A.place(planes[n], norms[n], push) for n in A.OPENINGS}
            t0 = time.time()
            areas, err = A.clip_areas(points, faces, placed, 'roi')
            dt = time.time() - t0
            if areas is None:
                print(f'  push {push:+6.2f}  {dt:6.1f}s  refused: {str(err)[:60]}', flush=True)
            else:
                print(f'  push {push:+6.2f}  {dt:6.1f}s  ' + '  '.join(
                    f'{n}={areas.get(n, float("nan")):8.2f}' for n in A.OPENINGS),
                    flush=True)


if __name__ == '__main__':
    main()
