"""A/B the two seed modes on the four auto_pass cases, on the production clip.

The question is not "which mask looks nicer" but "does the cap area move".
b01-b24 baselines were produced with ROI seeding, so if loop seeding changes
the cap area on a case that already passes, the two modes are not
interchangeable and the switch needs a decision, not a default flip.

Prints, per case and opening: cap area under each mode, the delta, and how many
negative-side components each mode selected.
"""
import json
import sys
from pathlib import Path

import numpy as np
import vtk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from connectivity_opened_surface import flood_mask, OPENINGS
from export_candidate_preview import triangle_arrays
from partitioned_surface import clip_and_cap

CASES = ('b01', 'b02', 'b03', 'b11')
ROOT = Path('D:/项目/鼻腔建模/work/06_auto_landmarks')


def cap_areas(points, faces, planes, selectors):
    p, f, patches, _ = clip_and_cap(points, faces, planes, selectors=selectors)
    xyz = p[f]
    out = {}
    for name in OPENINGS:
        t = xyz[patches == name]
        if len(t):
            out[name] = float(np.linalg.norm(
                np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() * .5)
    return out


def main():
    print(f'{"case":6s} {"opening":20s} {"roi mm2":>9s} {"loop mm2":>9s} '
          f'{"delta":>8s} {"rel":>7s}  comps(roi/loop)')
    worst = 0.0
    for case in CASES:
        obj = json.loads((ROOT / case / 'landmarks.json').read_text(encoding='utf-8'))
        reader = vtk.vtkXMLPolyDataReader()
        reader.SetFileName(f'C:/ts_work/batch27_surfaces/{case}/source_surface.vtp')
        reader.Update()
        points, faces = triangle_arrays(reader.GetOutput())
        planes = {n: {'point_lps_mm': obj['landmarks'][n]['point_lps_mm'],
                      'normal_lps': obj['landmarks'][n]['normal_lps'],
                      'roi_lps_mm': obj['landmarks'][n]['roi_lps_mm'],
                      'keep_positive': True} for n in OPENINGS}
        sel = {}
        comps = {}
        for mode in ('roi', 'loop'):
            for n in OPENINGS:
                m, note = flood_mask(points, faces, planes[n], seed_mode=mode)
                sel[(mode, n)] = m
                comps[(mode, n)] = note['negative_components_reached']
        for n in OPENINGS:
            a_roi = cap_areas(points, faces, planes,
                              {k: sel[('roi', k)] for k in OPENINGS})
            a_loop = cap_areas(points, faces, planes,
                               {k: sel[('loop', k)] for k in OPENINGS})
            r, l = a_roi.get(n), a_loop.get(n)
            if r is None or l is None:
                print(f'{case:6s} {n:20s} roi={r} loop={l}  MISSING')
                continue
            d = l - r
            rel = d / r if r else float('nan')
            worst = max(worst, abs(rel))
            print(f'{case:6s} {n:20s} {r:9.2f} {l:9.2f} {d:+8.2f} {rel:+6.2%}  '
                  f'{comps[("roi", n)]}/{comps[("loop", n)]}')
    print(f'\nworst relative cap-area change: {worst:.2%}')


if __name__ == '__main__':
    main()
