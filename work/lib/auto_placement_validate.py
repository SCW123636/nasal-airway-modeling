"""Does the airway-lumen onset survive threshold changes, and does it drive a
passing end-to-end clip?

Two separate questions, deliberately kept apart:

A. Sensitivity. AREA_ON=50 mm2 was picked before the scan was run and never
   tuned. If the detected position moves when the threshold moves, the
   criterion is a fit to the five reviewed positions rather than a detector.
   So sweep the threshold and report the spread.

B. End-to-end. A criterion that locates a plane but produces a failing mesh is
   useless. Run the production clip_and_cap at onset + delta for several deltas
   and report pass/fail, patch areas and removed volume per case.

The connectivity selector follows the plane: its ROI box is defined relative to
the plane it belongs to, so translating the plane translates the ROI.
"""
import json
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
from auto_opening_placement import detect_onset, plane_basis, SRC, CASES

THRESHOLDS = (20.0, 35.0, 50.0, 75.0, 100.0, 150.0)
DELTAS = (0.0, 0.25, 0.5, 1.0, 2.0)


def shift_plane(spec, n, delta):
    o = np.asarray(spec['point_lps_mm'], float)
    moved = dict(spec)
    moved['point_lps_mm'] = (o + delta * n).tolist()
    roi = spec['roi_lps_mm']
    moved['roi_lps_mm'] = {
        'min': (np.asarray(roi['min'], float) + delta * n).tolist(),
        'max': (np.asarray(roi['max'], float) + delta * n).tolist(),
    }
    return moved


def main():
    work = Path(__file__).resolve().parents[1]
    out = work / '08_auto_placement'
    out.mkdir(exist_ok=True)
    mgr = CaseManager(Path('C:/ts_work/project_cases'))
    store = MedicalReviewStore(mgr, work / '06_auto_landmarks')
    sens, e2e = [], []
    try:
        for case in CASES:
            config, _ = load_adopted(store, case)
            reader = vtk.vtkXMLPolyDataReader()
            reader.SetFileName(str(SRC / case / 'source_surface.vtp'))
            reader.Update()
            points, faces = triangle_arrays(reader.GetOutput())
            planes = {k: config['planes_lps'][k] for k in OPENINGS}
            norms = {}
            for k in OPENINGS:
                n, _, _ = plane_basis(planes[k]['normal_lps'])
                norms[k] = n

            for thr in THRESHOLDS:
                for name in OPENINGS:
                    spec = planes[name]
                    onset, _, _ = detect_onset(points, faces,
                                               np.asarray(spec['point_lps_mm'], float),
                                               norms[name], area_on=thr)
                    sens.append({'case': case, 'opening': name, 'area_on_mm2': thr,
                                 'onset_offset_mm': None if onset is None else round(onset, 2)})

            for delta in DELTAS:
                specs = {}
                for name in OPENINGS:
                    spec = planes[name]
                    o = np.asarray(spec['point_lps_mm'], float)
                    onset, _, _ = detect_onset(points, faces, o, norms[name])
                    if onset is None:
                        specs = None
                        break
                    specs[name] = shift_plane(spec, norms[name], onset + delta)
                row = {'case': case, 'delta_mm': delta}
                if specs is None:
                    row['status'] = 'no_onset'
                    e2e.append(row)
                    print(f'{case} delta={delta}: no onset', flush=True)
                    continue
                try:
                    sel = {k: flood_mask(points, faces, specs[k])[0] for k in OPENINGS}
                    p, f, patches, qc = clip_and_cap(points, faces, specs, selectors=sel)
                    qc = qc.get('technical_qc', qc)
                    xyz = p[f]
                    areas = {}
                    for name in OPENINGS:
                        t = xyz[patches == name]
                        if len(t):
                            areas[name] = round(float(np.linalg.norm(
                                np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() * .5), 2)
                    row.update(status='pass', patch_areas_mm2=areas,
                               signed_volume_mm3=round(qc['signed_volume_mm3'], 1))
                except ValueError as exc:
                    row.update(status='fail', reason=str(exc))
                e2e.append(row)
                print(f"{case} delta={delta}: {row['status']} "
                      f"{row.get('patch_areas_mm2', row.get('reason', ''))}", flush=True)
    finally:
        mgr.pool.shutdown(wait=True)

    by_thr = {}
    for r in sens:
        by_thr.setdefault(r['area_on_mm2'], []).append(r['onset_offset_mm'])
    summary = {t: {'found': sum(x is not None for x in v),
                   'min': min([x for x in v if x is not None], default=None),
                   'max': max([x for x in v if x is not None], default=None)}
               for t, v in by_thr.items()}
    ref = {r['area_on_mm2']: r['onset_offset_mm'] for r in sens if r['area_on_mm2'] == 50.0}
    drift = []
    for r in sens:
        b = ref.get((r['case'], r['opening']))
        if r['onset_offset_mm'] is not None and b is not None:
            drift.append(round(r['onset_offset_mm'] - b, 2))
    payload = {'schema': 'auto_placement_validation/v1',
               'threshold_sensitivity': summary,
               'onset_drift_vs_50mm2': {'n': len(drift),
                                        'min': min(drift) if drift else None,
                                        'max': max(drift) if drift else None},
               'sensitivity_rows': sens, 'end_to_end_rows': e2e}
    (out / 'validation.json').write_text(json.dumps(payload, indent=2), encoding='utf-8')
    print(json.dumps({'threshold_sensitivity': summary,
                      'onset_drift_vs_50mm2': payload['onset_drift_vs_50mm2']}, indent=2))
    for d in DELTAS:
        rows = [r for r in e2e if r['delta_mm'] == d]
        ok = sum(r['status'] == 'pass' for r in rows)
        print(f'delta={d}: pass {ok}/{len(rows)}')


if __name__ == '__main__':
    main()