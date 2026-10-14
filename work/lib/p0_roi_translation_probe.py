"""p0 only: does keeping the ROI box fixed rescue the failing case?

p0 failed every delta with 'no negative-side seed inside the reviewed ROI'.
Two candidate causes, and they are distinguishable:

  (a) an artefact - auto_placement_validate.shift_plane translates the ROI with
      the plane, so moving the plane 3.25 mm up may simply carry the seed box
      off the negative side. Fix: keep the reviewed ROI fixed.
  (b) real - p0's reviewed outlet point is itself questionable (it sits 3.2 mm
      above the nostril planes, unlike p2/p3t1 whose direction is correct), so
      no shift fixes it.

Only p0 is run, and only through the production functions.
"""
import sys
from pathlib import Path

import numpy as np
import vtk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_reviewed_surface_drafts import load_adopted
from ct_case_pipeline import CaseManager
from medical_review import MedicalReviewStore
from export_candidate_preview import triangle_arrays
from partitioned_surface import clip_and_cap
from connectivity_opened_surface import flood_mask, OPENINGS
from auto_opening_placement import detect_onset, plane_basis, SRC


def move_plane_only(spec, n, delta):
    """Translate the plane, leave the reviewed ROI where the reviewer put it."""
    o = np.asarray(spec['point_lps_mm'], float)
    moved = dict(spec)
    moved['point_lps_mm'] = (o + delta * n).tolist()
    return moved


def main():
    work = Path(__file__).resolve().parents[1]
    mgr = CaseManager(Path('C:/ts_work/project_cases'))
    store = MedicalReviewStore(mgr, work / '06_auto_landmarks')
    try:
        config, _ = load_adopted(store, 'p0')
        reader = vtk.vtkXMLPolyDataReader()
        reader.SetFileName(str(SRC / 'p0' / 'source_surface.vtp'))
        reader.Update()
        points, faces = triangle_arrays(reader.GetOutput())
        planes = {k: config['planes_lps'][k] for k in OPENINGS}
        for delta in (0.0, 0.25, 0.5, 1.0, 2.0):
            specs = {}
            for name in OPENINGS:
                spec = planes[name]
                n, _, _ = plane_basis(spec['normal_lps'])
                o = np.asarray(spec['point_lps_mm'], float)
                onset, _, _ = detect_onset(points, faces, o, n)
                specs[name] = move_plane_only(spec, n, onset + delta)
            try:
                sel = {k: flood_mask(points, faces, specs[k])[0] for k in OPENINGS}
                p, f, patches, qc = clip_and_cap(points, faces, specs, selectors=sel)
                xyz = p[f]
                areas = {}
                for name in OPENINGS:
                    t = xyz[patches == name]
                    if len(t):
                        areas[name] = round(float(np.linalg.norm(
                            np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() * .5), 2)
                print(f'p0 delta={delta}: pass {areas}', flush=True)
            except ValueError as exc:
                print(f'p0 delta={delta}: fail {exc}', flush=True)
    finally:
        mgr.pool.shutdown(wait=True)


if __name__ == '__main__':
    main()