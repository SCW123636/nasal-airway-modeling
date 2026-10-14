"""Why does clip_and_cap reject the rim-band selection on b05/b15/b18?

Baseline (roi) never got here: the outlet raised seed_lost before clip ran.
With hybrid the outlet is seeded and clip_and_cap runs for the first time, then
refuses. Two distinct messages showed up:

  b15  'Cut boundaries must be closed degree-two loops'      (boundary_loops)
  b18  'nasopharynx_outlet: unexpected boundary outside ...' (coplanarity)

Both are topological, i.e. about the SHAPE of the deleted region, not its size.
So the question is whether the rim-band selection deletes a region whose cut
boundary is a clean coplanar loop.

Discriminators, in order of information value:

  1. single plane vs all three. If one plane alone clips fine but the sequence
     does not, the problem is interaction (an earlier cap), not the selection.
  2. component breakdown of every selection: how many negative components the
     seeds reach, where their centroids sit, how far apart. The docstring of
     loop_seed_vertices already warns that a rim band can drag in a fragment
     from a different opening; this measures whether it did.
  3. rim geometry: which section loop was picked, how many rim triangles.

Read-only. Writes nothing but stdout.
"""
import json
import sys
from pathlib import Path

import numpy as np
import vtk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_candidate_preview import triangle_arrays
from auto_opening_placement import detect_onset, plane_basis
from connectivity_opened_surface import flood_mask, signed_of, OPENINGS
from partitioned_surface import clip_and_cap
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

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


def component_report(points, faces, mask):
    """Negative-side components the mask's selected vertices live in."""
    e = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    g = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])),
                   shape=(len(points), len(points))).tocsr()
    _, labels = connected_components(g, directed=False)
    sel_labels = np.unique(labels[mask])
    out = []
    for lb in sel_labels:
        idx = np.where(mask & (labels == lb))[0]
        if not len(idx):
            continue
        c = points[idx].mean(axis=0)
        out.append((int(len(idx)), [round(float(v), 1) for v in c]))
    out.sort(reverse=True)
    return out


def try_clip(points, faces, planes, sels, tag):
    try:
        p, f, patches, qc = clip_and_cap(points, faces, planes, selectors=sels)
    except ValueError as exc:
        print(f'    {tag}: FAIL  {exc}')
        return None
    xyz = p[f]
    areas = {}
    for n in planes:
        t = xyz[patches == n]
        if len(t):
            areas[n] = round(float(np.linalg.norm(
                np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() * .5), 2)
    print(f'    {tag}: OK  areas={areas}')
    return areas


for case in CASES:
    print('=' * 74)
    print(case)
    points, faces, planes = load(case)
    norms = {k: plane_basis(planes[k]['normal_lps'])[0] for k in OPENINGS}
    onsets = {}
    for n in OPENINGS:
        o = np.asarray(planes[n]['point_lps_mm'], float)
        onsets[n], _, _ = detect_onset(points, faces, o, norms[n])
    print('  onsets:', {k: (None if v is None else round(v, 2)) for k, v in onsets.items()})

    from auto_opening_pipeline import build_placed
    layouts = [('reviewed plane (offset 0)', planes),
               ('placed = onset + 0.5', build_placed(planes, norms, onsets,
                                                     {k: 0.5 for k in OPENINGS}))]
    for label, pl in layouts:
        print(f'  --- {label}')
        for mode in ('roi', 'hybrid'):
            sels, notes = {}, {}
            try:
                for n in OPENINGS:
                    sels[n], notes[n] = flood_mask(points, faces, pl[n], seed_mode=mode)
            except ValueError as exc:
                print(f'    {mode}: flood refused -> {exc}')
                continue
            for n in OPENINGS:
                note = notes[n]
                comps = component_report(points, faces, sels[n])
                fall = 'FALLBACK' if note.get('roi_seed_unavailable_fallback_to_rim_band') else ''
                print(f'    {n:20s} seeds={note["seed_vertices"]:5d} '
                      f'selected={note["selected_vertices"]:5d} comps={len(comps)} {fall}')
                for nv, c in comps:
                    print(f'        component {nv:5d} verts, centroid {c}')
                if 'rim_band' in note:
                    band = note['rim_band']
                    print(f'        rim: loops={band.get("section_loops_at_plane")} '
                          f'used={band.get("loop_used")} tris={band.get("rim_triangles")} '
                          f'band_verts={band.get("rim_band_vertices")} '
                          f'loop_areas={band.get("loop_areas_mm2")}')
            for n in OPENINGS:
                try_clip(points, faces, {n: pl[n]}, {n: sels[n]}, f'{mode} single {n}')
            try_clip(points, faces, {n: pl[n] for n in OPENINGS}, sels, f'{mode} full sequence')
