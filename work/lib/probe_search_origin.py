"""What a 'reviewed'-anchored search would land on, per opening.

Read-only. For each case it reports the cap areas the reviewed plane itself
produces (push 0.0 / +0.25 / +0.5 mm) next to the decision the full stage-5
report makes under --search-origin reviewed, so the batch is only launched once
the three known failures are seen to move for the reason we think they do.

Usage: probe_search_origin.py [case ...]
"""
import json
import sys
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


def load(case):
    r = vtk.vtkXMLPolyDataReader()
    r.SetFileName(str(SURF / case / 'source_surface.vtp'))
    r.Update()
    points, faces = triangle_arrays(r.GetOutput())
    o = json.loads((LM / case / 'landmarks.json').read_text(encoding='utf-8'))
    planes = {n: {'point_lps_mm': o['landmarks'][n]['point_lps_mm'],
                  'normal_lps': o['landmarks'][n]['normal_lps'],
                  'roi_lps_mm': o['landmarks'][n]['roi_lps_mm'],
                  'keep_positive': True} for n in A.OPENINGS}
    return points, faces, planes


def main():
    cases = sys.argv[1:] or ['b15', 'b18', 'b05', 'b02']
    for case in cases:
        points, faces, planes = load(case)
        norms = {k: plane_basis(planes[k]['normal_lps'])[0] for k in A.OPENINGS}
        onsets = {}
        for n in A.OPENINGS:
            p = np.asarray(planes[n]['point_lps_mm'], float)
            onsets[n], _, _ = detect_onset(points, faces, p, norms[n])
        print('=' * 72)
        print(f'{case}  onsets={ {k: (None if v is None else round(v, 2)) for k, v in onsets.items()} }')
        for push in (0.0, 0.25, 0.5):
            placed = {n: A.place(planes[n], norms[n], push) for n in A.OPENINGS}
            areas, err = A.clip_areas(points, faces, placed, 'roi')
            if areas is None:
                print(f'  push {push:+.2f}: clip refused -> {err}')
            else:
                print(f'  push {push:+.2f}: ' +
                      '  '.join(f'{n}={areas.get(n, float("nan")):.2f}' for n in A.OPENINGS))
        for origin in ('onset', 'reviewed'):
            rep = A.process(case, points, faces, {'planes_lps': planes},
                            Path('.tools/probe_search_origin'), origin=origin)
            print(f'  process origin={origin:8s} -> {rep["decision"]:9s} '
                  f'areas={rep.get("patch_areas_mm2")} '
                  f'offset_from_reviewed={rep.get("offset_from_reviewed_mm")}')
            if rep['decision'] != 'auto_pass':
                for e in rep['escalations']:
                    print(f'      {e["opening"]} | {e["reason"]} | {str(e["detail"])[:110]}')


if __name__ == '__main__':
    main()
