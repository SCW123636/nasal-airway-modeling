"""Automatic opening-plane placement, validated against the five reviewed cases.

The reviewed configurations give us ground truth for a small number of
openings, so this asks a narrow question first: is there a measurable, purely
geometric quantity whose optimum lands on the reviewed plane? Only if the answer
holds is it worth automating; a heuristic that cannot reproduce five
hand-reviewed positions should not be trusted on twenty-seven new cases.

Everything here is a placement study. It never approves anatomy and never
authorises a solver.
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
from connectivity_opened_surface import signed_of, flood_mask, OPENINGS

SRC = Path('C:/ts_work/reviewed_surface_drafts_20261008_r3')
SHIFT_MM = (-20, -16, -12, -8, -6, -4, -3, -2, -1, 0, 1, 2, 3, 4, 6, 8, 12, 16, 20)


def cross_section(points, faces, spec, *, tolerance_mm=1e-7):
    """Area of the wall cross-section cut by the plane, per kept side.

    Cross-section area is the quantity that defines an opening: it must be large
    enough to pass air, small enough not to be a slab. Reported for both sides so
    a plane that cuts far outside the airway is visible as a spike.
    """
    n = np.asarray(spec['normal_lps'], float)
    n = n / np.linalg.norm(n)
    o = np.asarray(spec['point_lps_mm'], float)
    s = (points - o) @ n
    v = points[faces]
    inside = np.all((v > -tolerance_mm) & (v < tolerance_mm), axis=2)
    count = inside.sum(axis=1)
    return count


def profile(points, faces, spec, name):
    """Scan the plane along its own normal and record what each position yields."""
    n = np.asarray(spec['normal_lps'], float)
    n = n / np.linalg.norm(n)
    o = np.asarray(spec['point_lps_mm'], float)
    rows = []
    for d in SHIFT_MM:
        moved = dict(spec)
        moved['point_lps_mm'] = (np.asarray(o, float) + d * n).tolist()
        try:
            mask, note = flood_mask(points, faces, moved)
        except ValueError as exc:
            rows.append({'shift_mm': d, 'status': 'no_seed', 'reason': str(exc)})
            continue
        neg = signed_of(points, moved) < 0
        sel_faces = int(mask.sum())
        # how many components were reached: a well-centred seed touches the
        # single airway lumen, an off-centre one fragments into many
        rows.append({'shift_mm': d, 'status': 'ok',
                     'seed_vertices': note['seed_vertices'],
                     'components_reached': note['negative_components_reached'],
                     'selected_vertices': sel_faces})
    return rows


def main():
    work = Path(__file__).resolve().parents[1]
    mgr = CaseManager(Path('C:/ts_work/project_cases'))
    store = MedicalReviewStore(mgr, work / '06_auto_landmarks')
    try:
        for case in ('p0', 'p1', 'p2', 'p3', 'p3t1'):
            config, _ = load_adopted(store, case)
            reader = vtk.vtkXMLPolyDataReader()
            reader.SetFileName(str(SRC / case / 'source_surface.vtp'))
            reader.Update()
            points, faces = triangle_arrays(reader.GetOutput())
            planes = {k: config['planes_lps'][k] for k in OPENINGS}
            print('=' * 22, case)
            for name in OPENINGS:
                rows = profile(points, faces, planes[name], name)
                ok = [r for r in rows if r['status'] == 'ok']
                if not ok:
                    print(f'   {name}: no valid shift')
                    continue
                best = min(ok, key=lambda r: r['components_reached'])
                at0 = next((r for r in ok if r['shift_mm'] == 0), None)
                print(f"   {name:18s} reviewed_shift=0 comps={at0['components_reached'] if at0 else 'NA'} "
                      f"seedV={at0['seed_vertices'] if at0 else 'NA'}")
                print('      comps by shift: ' + '  '.join(
                    f"{r['shift_mm']:+d}:{r['components_reached']}" for r in ok))
    finally:
        mgr.pool.shutdown(wait=True)


if __name__ == '__main__':
    main()