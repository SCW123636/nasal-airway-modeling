"""T-047 step 3: opening placement on the b01 extended-domain surface.

Reuses the production auto_opening_pipeline.process worker UNMODIFIED, driven
with a patched opening set:

  nostril_L / nostril_R          planes + 80 mm2 targets + [40,140] band, all
                                 identical to production (nostril anatomy is
                                 untouched by the oropharynx extension, so the
                                 caps must reproduce batch27_opening/b01.json's
                                 80.08 / 80.08 - a built-in regression check).
  oropharynx_truncation_outlet   NEW. Plane = axial cut 0.5 mm above the bottom
                                 voxel-centre plane of the extended air mask
                                 (the scan's inferior face region); normal +z,
                                 keep_positive (domain above). Target = 10 mm2
                                 FLOOR (not a physiological target: the natural
                                 truncation cap is ~139 mm2 for b01, far above
                                 the floor, so the bisection never fires and the
                                 plane stays at the anchor = maximal domain).
                                 Band [10,600] records the actual area.

Monkey-patching module-level dicts in the imported auto_opening_pipeline is a
T-047-local experiment device: production files are not modified. The honest
opening name flows into auto_placed.vtp boundary_patch labels and downstream
mesh/solver patch names.

Outputs (staging C:/ts_work/t047_b01_oroext, copied to outputs/T-047/b01_oroext):
  auto_placed.vtp (on auto_pass), t047_opening_report.json
"""
import datetime
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import SimpleITK as sitk
import vtk

sys.path.insert(0, 'D:/项目/鼻腔建模/work/lib')
from export_candidate_preview import triangle_arrays
import auto_opening_pipeline as aop

CASE = sys.argv[1] if len(sys.argv) > 1 else 'b01'
RUN = f'{CASE}_oroext'
NEW = 'oropharynx_truncation_outlet'
STAGING = Path(f'C:/ts_work/t054_{CASE}_oroext')
OUT = Path(__file__).resolve().parent / f'{CASE}_oroext'
LM_PATH = Path(f'D:/项目/鼻腔建模/work/06_auto_landmarks/{CASE}/landmarks.json')
PROD_REPORT = Path(f'C:/ts_work/batch27_opening/{CASE}.json')

CUT_ABOVE_BOTTOM_MM = 0.5
ROI_MARGIN_XY_MM = 3.0


def build_planes():
    lm = json.loads(LM_PATH.read_text(encoding='utf-8'))['landmarks']
    planes = {}
    for name in ('nostril_L', 'nostril_R'):
        v = lm[name]
        planes[name] = {'point_lps_mm': v['point_lps_mm'],
                        'normal_lps': v['normal_lps'],
                        'roi_lps_mm': v['roi_lps_mm'],
                        'keep_positive': True}
    m = sitk.ReadImage(str(STAGING / 'extended_air_mask.nii.gz'))
    arr = sitk.GetArrayFromImage(m)  # (z,y,x)
    assert arr[0].any(), 'bottom slice has no air - mask does not reach scan face'
    sp, org = m.GetSpacing(), m.GetOrigin()
    yy, xx = np.where(arr[0] > 0)
    xs, ys = org[0] + xx * sp[0], org[1] + yy * sp[1]
    z_bot, z_cut = float(org[2]), float(org[2]) + CUT_ABOVE_BOTTOM_MM
    roi = {'min': [float(xs.min()) - ROI_MARGIN_XY_MM,
                   float(ys.min()) - ROI_MARGIN_XY_MM, z_bot - 0.8],
           'max': [float(xs.max()) + ROI_MARGIN_XY_MM,
                   float(ys.max()) + ROI_MARGIN_XY_MM, z_cut + 0.7]}
    planes[NEW] = {'point_lps_mm': [float(xs.mean()), float(ys.mean()), z_cut],
                   'normal_lps': [0.0, 0.0, 1.0],
                   'roi_lps_mm': roi, 'keep_positive': True}
    return planes, {'bottom_air_voxels': int(arr[0].sum()),
                    'z_bottom_center_mm': z_bot, 'z_cut_mm': z_cut}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    planes, cut_info = build_planes()

    aop.OPENINGS = ('nostril_L', 'nostril_R', NEW)
    aop.CAP_TARGET_MM2 = {'nostril_L': 80.0, 'nostril_R': 80.0, NEW: 10.0}
    aop.AREA_BAND_MM2 = {'nostril_L': (40.0, 140.0), 'nostril_R': (40.0, 140.0),
                         NEW: (10.0, 600.0)}

    reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(str(STAGING / 'extended_surface.vtp'))
    reader.Update()
    points, faces = triangle_arrays(reader.GetOutput())

    # allow_onset_outlier=True: with the extended surface the nostril onset sweep
    # (a +/-30 mm ray along the nostril normal) now crosses the added oropharynx
    # tube ~20 mm below and reports a spurious onset there (-19.5/-20.0 mm on b01).
    # With origin='reviewed' the onset drives NO position (documented in
    # onset_verdict); demoting to onset_flags is the production opt-in arm and
    # every admission is recorded in the report.
    rep = aop.process(RUN, points, faces, {'planes_lps': planes}, STAGING,
                      seed_mode='roi', origin='reviewed', allow_onset_outlier=True)

    # regression vs production b01 (nostrils must reproduce; extension adds nothing near them)
    prod = json.loads(PROD_REPORT.read_text(encoding='utf-8'))
    cmp = {'production_b01': prod['patch_areas_mm2'],
           'extended_b01': rep.get('patch_areas_mm2')}
    if rep.get('patch_areas_mm2'):
        cmp['nostril_abs_diff_mm2'] = {
            k: round(abs(rep['patch_areas_mm2'].get(k, 0) - prod['patch_areas_mm2'][k]), 3)
            for k in ('nostril_L', 'nostril_R')}

    rep['t047'] = {
        'created': datetime.datetime.now().astimezone().isoformat(),
        'task': f'T-054 oropharynx-extension opening placement, case={CASE}',
        'new_opening': NEW,
        'outlet_role': 'engineering_truncation_at_scan_inferior_face',
        'cut_info': cut_info,
        'target_semantics': 'nostril targets are production 80 mm2; the truncation '
                            'outlet target is a 10 mm2 FLOOR so the bisection never '
                            'fires and the plane stays at the maximal-domain anchor; '
                            'the recorded cap is the natural truncation area',
        'regression_vs_production': cmp,
        'missing_downstream': 'hypopharynx+larynx not in any scan (T-048 closed loop); '
                              'delta_p biased low by the missing downstream resistance',
        'clinical_status': 'generalisation_test_only_no_human_review',
    }
    (STAGING / 't047_opening_report.json').write_text(
        json.dumps(rep, indent=2, ensure_ascii=False), encoding='utf-8')

    for f in ('t047_opening_report.json',):
        shutil.copy2(STAGING / f, OUT / f)
    placed = STAGING / RUN / 'auto_placed.vtp'
    if placed.is_file():
        (OUT / RUN).mkdir(exist_ok=True)
        shutil.copy2(placed, OUT / RUN / 'auto_placed.vtp')

    print('decision:', rep['decision'])
    print('patch_areas_mm2:', rep.get('patch_areas_mm2'))
    print('offset_from_reviewed_mm:', rep.get('offset_from_reviewed_mm'))
    print('regression:', json.dumps(cmp, ensure_ascii=False))
    if rep.get('escalations'):
        print('escalations:', json.dumps(rep['escalations'], ensure_ascii=False)[:600])
    print('onset_flags:', json.dumps(rep.get('onset_flags'), ensure_ascii=False)[:300])


if __name__ == '__main__':
    main()
