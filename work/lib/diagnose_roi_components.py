"""Which components does each seed mode select, and are they the same anatomy?

The ROI mode passed on b01-b11 etc, so its component set is the de-facto
reference. The rim-band mode selects more of them (b01 nostril_L: 3 vs 2,
outlet: 6 vs 4). This prints every selected component with its signed-distance
range and centroid, so the extras can be judged: wall fragments next to the
plane, or a different cavity that the ROI box used to exclude.
"""
import json
import sys
from pathlib import Path

import numpy as np
import vtk
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

sys.path.insert(0, str(Path(__file__).resolve().parent))
from connectivity_opened_surface import flood_mask, signed_of, OPENINGS
from export_candidate_preview import triangle_arrays


def components(points, faces, spec):
    s = signed_of(points, spec)
    negative = s < 0
    e = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    e = e[negative[e].all(axis=1)]
    g = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])),
                   shape=(len(points), len(points))).tocsr()
    _, labels = connected_components(g, directed=False)
    return negative, labels


def main():
    for case in sys.argv[1:] or ['b01']:
        obj = json.loads((Path('D:/项目/鼻腔建模/work/06_auto_landmarks') / case
                          / 'landmarks.json').read_text(encoding='utf-8'))
        reader = vtk.vtkXMLPolyDataReader()
        reader.SetFileName(f'C:/ts_work/batch27_surfaces/{case}/source_surface.vtp')
        reader.Update()
        points, faces = triangle_arrays(reader.GetOutput())
        print(f'=== {case}: {len(points)} vertices')
        for name in OPENINGS:
            lm = obj['landmarks'].get(name)
            if not lm or not lm.get('point_lps_mm'):
                continue
            sp = {'point_lps_mm': lm['point_lps_mm'], 'normal_lps': lm['normal_lps'],
                  'roi_lps_mm': lm['roi_lps_mm'], 'keep_positive': True}
            negative, labels = components(points, faces, sp)
            n = np.asarray(sp['normal_lps'], float)
            n /= np.linalg.norm(n)
            o = np.asarray(sp['point_lps_mm'], float)
            sd = (points - o) @ n
            lo = np.asarray(lm['roi_lps_mm']['min'], float)
            hi = np.asarray(lm['roi_lps_mm']['max'], float)
            print(f'  {name}  (negative side total: {int(negative.sum())} verts)')
            modes = {}
            for mode in ('roi', 'loop'):
                try:
                    m, note = flood_mask(points, faces, sp, seed_mode=mode)
                    modes[mode] = (m, note)
                except ValueError as exc:
                    print(f'    {mode:5s} FAILS: {exc}')
            ref = modes.get('roi', (None, None))[0]
            for mode in ('roi', 'loop'):
                if mode not in modes:
                    continue
                m, note = modes[mode]
                sel_labels = sorted(set(int(x) for x in labels[m]))
                print(f'    {mode:5s}: {int(m.sum()):5d} verts in '
                      f'{len(sel_labels)} component(s) {sel_labels}')
                for lb in sel_labels:
                    cm = negative & (labels == lb)
                    if not cm.any():
                        continue
                    xyz = points[cm]
                    d = sd[cm]
                    inroi = ((xyz >= lo) & (xyz <= hi)).all(1).mean()
                    extra = (ref is not None and mode == 'loop'
                             and not (cm & ref).any())
                    print(f'        comp {lb:6d}: {int(cm.sum()):5d} verts, '
                          f'sd {d.min():7.2f}..{d.max():6.2f}, '
                          f'centroid {np.round(xyz.mean(0), 1).tolist()}, '
                          f'{inroi:5.0%} of its verts inside the ROI box'
                          f'{"   <== NOT selected by ROI" if extra else ""}')


if __name__ == '__main__':
    main()
