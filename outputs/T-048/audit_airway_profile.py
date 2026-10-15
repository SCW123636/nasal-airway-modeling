"""T-048 airway cross-section profile down the visible throat (oropharynx -> scan inferior face).

Decisive measurement for the throat-extension requirement: per-slice airway area
(oropharynx label AND CT < -300 HU, the project's air definition) along z.

Axis semantics (LPS, nibabel (x,y,z) arrays, identity direction asserted):
  - z index 0            = scan INFERIOR face (neck side)
  - z index nz-1         = scan SUPERIOR face (head side)
  - zz.min()             = label INFERIOR end (toward the larynx)
  - zz.max()             = label SUPERIOR end (junction toward the nasopharynx)

(The 2026-10-16 00:5x version named zz.min() "top" and zz.max() "bottom",
inverting every downstream field name. The numbers were right; the names were
wrong, and one derived claim ("still wide at scan bottom") was misread from it.
Fixed here and the JSON regenerated; the old file is superseded, not patched.)

If the airway narrows toward the scan inferior face, that narrowing could be the
laryngeal inlet (a natural outlet level); if it stays wide, the scan cuts
mid-oropharynx and an outlet there can only be an engineering truncation
(honestly labelled) or an anatomical level picked by review.

Read-only; loads CT per case and frees it. LPS identity direction asserted.
"""
import json
import sys
import datetime
from pathlib import Path

import numpy as np
import nibabel as nib

BASE = Path('C:/ts_work')
CASES_B = [f'b{i:02d}' for i in range(1, 25)]
CASES_P = ['p0', 'p1', 'p2', 'p3', 'p3t1']
HU_AIR = -300.0


def profile_case(case):
    d = BASE / case
    ct = nib.load(str(d / 'ct.nii.gz'))
    affine = np.asarray(ct.affine, dtype=float)
    if not np.allclose(affine[:3, :3], np.diag(np.diag(affine[:3, :3])), atol=1e-6):
        return {'case': case, 'error': 'non-identity direction'}
    ct_arr = np.asarray(ct.dataobj).astype(np.float32)
    oro = nib.load(str(d / 'masks' / 'oropharynx.nii.gz'))
    oro_arr = np.asarray(oro.dataobj) > 0
    zooms = ct.header.get_zooms()
    vox_area_mm2 = float(zooms[0] * zooms[1])
    air = oro_arr & (ct_arr < HU_AIR)
    # nibabel array is (x,y,z): collapse axes 0,1 to leave the z (slice) axis
    zz = np.where(oro_arr.any(axis=(0, 1)))[0]
    if not len(zz):
        return {'case': case, 'error': 'empty oropharynx label'}
    inf_end = int(zz.min())   # label inferior end (larynx side)
    sup_end = int(zz.max())   # label superior end (nasopharynx junction side)
    nz = ct_arr.shape[2]
    # per-slice airway area from the label inferior end up to the LAST scan slice
    areas = []
    for k in range(inf_end, nz):
        areas.append(float((air[:, :, k]).sum()) * vox_area_mm2)
    del ct_arr, oro_arr, air
    z_mm = [float(affine[2, 3] + k * zooms[2]) for k in range(inf_end, nz)]
    i_sup = sup_end - inf_end
    lbl = areas[:i_sup + 1]
    tube_max = max(lbl)
    return {'case': case,
            'spacing_xyz_mm': [float(z) for z in zooms],
            'oro_label_inferior_k': inf_end, 'oro_label_superior_k': sup_end, 'nz': int(nz),
            'z_mm': z_mm, 'area_mm2': areas,
            'area_at_label_inferior_end_mm2': areas[0],
            'area_at_label_superior_end_mm2': areas[i_sup],
            'area_at_scan_superior_face_mm2': areas[-1],
            'tube_max_area_mm2': tube_max,
            'inferior_to_tube_max_ratio': (areas[0] / tube_max) if tube_max > 0 else None,
            'min_area_mm2': min(areas),
            'min_area_at_mm_from_inferior_end': z_mm[int(np.argmin(areas))] - z_mm[0],
            'visible_oropharynx_length_mm': abs(z_mm[i_sup] - z_mm[0])}


def main():
    only = sys.argv[1:] or None
    cases = [c for c in CASES_B + CASES_P if not only or c in only]
    report = {'created': datetime.datetime.now().astimezone().isoformat(),
              'scope': 'T-048 throat airway cross-section profile; read-only',
              'air_definition': f'oropharynx label AND CT < {HU_AIR} HU',
              'axis_semantics': 'z index 0 = scan inferior face; areas run inferior -> superior',
              'cases': {}}
    for c in cases:
        r = profile_case(c)
        report['cases'][c] = r
        if 'error' in r:
            print(f"{c:5s} ERROR {r['error']}", flush=True)
            continue
        print(f"{c:5s} z {r['z_mm'][0]:8.1f}->{r['z_mm'][-1]:8.1f} mm "
              f"({len(r['z_mm'])} sl) area@inf={r['area_at_label_inferior_end_mm2']:7.1f} "
              f"area@sup={r['area_at_label_superior_end_mm2']:7.1f} "
              f"tube_max={r['tube_max_area_mm2']:7.1f} "
              f"inf/max={r['inferior_to_tube_max_ratio']:.2f} "
              f"len={r['visible_oropharynx_length_mm']:5.1f}mm",
              flush=True)
    out = Path(__file__).resolve().parent / 'airway_profile_throat.json'
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print('written:', out)


if __name__ == '__main__':
    main()
