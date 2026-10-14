"""Does anchoring the fallback seed on the reviewed-plane STRUCTURE fix b15?

Measured on b15: with the plane at onset+0.5 the reviewed ROI holds no
negative-side vertex, the rim-band fallback fires, and it seeds the wrong
structure - the selected component's centroid lands at y=-99.5, in the nostril
region, where the outlet's real component sits at y=-43.4, 56 mm away. The single
plane still "clips" (a 87.89 mm2 fragment that is not the outlet); only the
three-plane sequence exposes it.

The rim band picks its own loop by area, and loop area carries no anatomical
meaning. The ROI box, wherever it still holds a seed, does carry that meaning for
that one plane. So the proposal tested here:

  anchor  flood from the reviewed ROI seed AT THE REVIEWED PLANE. That yields the
          target component V_ref. The box is used once, where it is known good.
  move    at the placed plane, keep only V_ref vertices that are on the negative
          side, and flood from those.

That removes the box from the moving part of the problem: the seed is the
structure itself, and it travels with the plane because the plane's own sign
decides which of its vertices are still seeds.

Reports, for b05/b15/b18 and a passing control (b02): the reference component,
the seed count after the move, the selected component's centroid (does it stay
near the reference?), and whether the three-plane sequence clips.

Read-only.
"""
import json
import sys
from pathlib import Path

import numpy as np
import vtk
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_candidate_preview import triangle_arrays
from auto_opening_placement import detect_onset, plane_basis
from auto_opening_pipeline import build_placed
from connectivity_opened_surface import flood_mask, signed_of, OPENINGS
from partitioned_surface import clip_and_cap

CASES = sys.argv[1:] or ['b02', 'b05', 'b15', 'b18']
SURF = Path('C:/ts_work/batch27_surfaces')
LAND = Path('work/06_auto_landmarks')


def load(case):
    r = vtk.vtkXMLPolyDataReader()
    r.SetFileName(str(SURF / case / 'source_surface.vtp'))
    r.Update()
    points, faces = triangle_arrays(r.GetOutput())
    o = json.loads((LAND / case / 'landmarks.json').read_text(encoding='utf-8'))
    planes = {n: {'point_lps_mm': o['landmarks'][n]['point_lps_mm'],
                  'normal_lps': o['landmarks'][n]['normal_lps'],
                  'roi_lps_mm': o['landmarks'][n]['roi_lps_mm'],
                  'keep_positive': True} for n in OPENINGS}
    return points, faces, planes


def graph(points, faces, spec):
    s = signed_of(points, spec)
    negative = s < 0
    e = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    e = e[negative[e].all(axis=1)]
    g = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])),
                   shape=(len(points), len(points))).tocsr()
    _, labels = connected_components(g, directed=False)
    return negative, labels


def flood_from(points, faces, spec, seed_vertices):
    negative, labels = graph(points, faces, spec)
    seeds = np.zeros(len(points), bool)
    seeds[np.asarray(seed_vertices, int)] = True
    seeds &= negative
    if not seeds.any():
        return None, 0
    chosen = negative & np.isin(labels, np.unique(labels[seeds]))
    return chosen, int(seeds.sum())


def centroid(points, mask):
    return [round(float(v), 1) for v in points[mask].mean(axis=0)] if mask.any() else None


for case in CASES:
    print('=' * 74)
    print(case)
    points, faces, planes = load(case)
    norms = {k: plane_basis(planes[k]['normal_lps'])[0] for k in OPENINGS}
    onsets = {}
    for n in OPENINGS:
        o = np.asarray(planes[n]['point_lps_mm'], float)
        onsets[n], _, _ = detect_onset(points, faces, o, norms[n])
    placed = build_placed(planes, norms, onsets, {k: 0.5 for k in OPENINGS})

    anchors, anchor_ok = {}, {}
    for n in OPENINGS:
        try:
            _, note = flood_mask(points, faces, planes[n], seed_mode='roi')
            m = flood_mask(points, faces, planes[n], seed_mode='roi')[0]
            anchors[n] = np.where(m)[0]
            anchor_ok[n] = True
            print(f'  anchor {n:20s} verts={len(anchors[n]):5d} '
                  f'centroid={centroid(points, m)}')
        except ValueError as exc:
            anchor_ok[n] = False
            print(f'  anchor {n:20s} unavailable ({exc})')

    for n in OPENINGS:
        if not anchor_ok[n]:
            continue
        m, nseed = flood_from(points, faces, placed[n], anchors[n])
        if m is None:
            print(f'  {n:20s} anchored seed: none of the reference vertices are '
                  f'negative at the placed plane')
            continue
        print(f'  {n:20s} anchored seed: seeds={nseed:5d} selected={int(m.sum()):5d} '
              f'centroid={centroid(points, m)}')

    sels = {}
    for n in OPENINGS:
        if not anchor_ok[n]:
            try:
                sels[n] = flood_mask(points, faces, placed[n], seed_mode='hybrid')[0]
            except ValueError:
                pass
            continue
        m, _ = flood_from(points, faces, placed[n], anchors[n])
        if m is not None:
            sels[n] = m
    if len(sels) == len(OPENINGS):
        try:
            p, f, patches, qc = clip_and_cap(points, faces,
                                             {n: placed[n] for n in OPENINGS},
                                             selectors=sels)
            xyz = p[f]
            areas = {}
            for n in OPENINGS:
                t = xyz[patches == n]
                if len(t):
                    areas[n] = round(float(np.linalg.norm(
                        np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]),
                        axis=1).sum() * .5), 2)
            print(f'  ANCHORED full sequence: OK  areas={areas}')
        except ValueError as exc:
            print(f'  ANCHORED full sequence: FAIL  {exc}')
    else:
        print('  ANCHORED: could not build all three selectors')
