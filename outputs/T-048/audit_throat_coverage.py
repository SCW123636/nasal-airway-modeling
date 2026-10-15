"""T-048 read-only throat-coverage audit for the b01-b24 sinus cohort (+ p-case reference).

Question (user requirement 2026-10-16): the CFD domain must extend backwards to the
throat, with the outlet cut at the throat. This script establishes, per case, what the
existing CT field of view actually covers below the current domain end
(nasopharynx/oropharynx interface):

  * oropharynx (class 12) label extent and whether it is truncated by the scan
    inferior face (project discipline: the scan edge is NOT a physiological outlet);
  * hypopharynx (class 13) label voxels (TS Dataset775 segments none in the p-cases);
  * soft palate truncation (free edge defines the oropharyngeal isthmus);
  * scan z range and spacing (CFD admissibility context).

Method reuses T-032 (outputs/T-032/inspect_lower_coverage.py): label bbox vs scan
bounds + inferior/superior face contact. No inference, no crop, no data mutation.
LPS identity direction asserted; non-identity cases are flagged, not transformed.
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
LABELS = ['nasal_cavity_left', 'nasal_cavity_right', 'nasopharynx',
          'oropharynx', 'hypopharynx', 'soft_palate']


def label_stats(arr, affine):
    """arr: nibabel array indexed (i,j,k) = (x,y,z). Returns voxel count, LPS bbox,
    face-contact counts. Axis order verified against T-032 SimpleITK known answers
    (p0 oropharynx: voxels 148837, z 0-107, inferior face 2236)."""
    xx, yy, zz = np.where(arr)  # nibabel: (i,j,k) = (x,y,z), NOT SimpleITK (z,y,x)
    nz = arr.shape[2]
    if not len(zz):
        return {'voxels': 0, 'bbox_ijk_zyx': None, 'bbox_lps_mm': None,
                'touch_inferior_face': 0, 'touch_superior_face': 0}
    lo = (int(zz.min()), int(yy.min()), int(xx.min()))
    hi = (int(zz.max()), int(yy.max()), int(xx.max()))

    def to_lps(zyx):
        v = np.array([zyx[2], zyx[1], zyx[0], 1.0])  # (z,y,x) idx -> (i,j,k) = (x,y,z)
        return (affine @ v)[:3]

    return {'voxels': int(len(zz)),
            'bbox_ijk_zyx': [list(lo), list(hi)],
            'bbox_lps_mm': [to_lps(lo).tolist(), to_lps(hi).tolist()],
            'touch_inferior_face': int((arr[:, :, 0] > 0).sum()),
            'touch_superior_face': int((arr[:, :, nz - 1] > 0).sum())}


def audit_case(case):
    d = BASE / case
    ct_path = d / 'ct.nii.gz'
    if not ct_path.exists():
        return {'case': case, 'missing': True}
    img = nib.load(str(ct_path))
    affine = np.asarray(img.affine, dtype=float)
    A3 = affine[:3, :3]
    identity_dir = bool(np.allclose(A3, np.diag(np.diag(A3)), atol=1e-6))
    zooms = [float(z) for z in img.header.get_zooms()]
    size = [int(s) for s in img.shape]
    # voxel outer bounds in LPS (index (i,j,k)=(x,y,z); k=0 is the inferior face for
    # identity LPS direction, confirmed by T-032 on real MPR views)
    corners = []
    for idx in [(0, 0, 0), tuple(s - 1 for s in size)]:
        v = np.array([idx[0], idx[1], idx[2], 1.0])  # (x,y,z) idx order
        corners.append((affine @ v)[:3])
    outer_lo = np.minimum(corners[0], corners[1]) - 0.5 * np.array(zooms)
    outer_hi = np.maximum(corners[0], corners[1]) + 0.5 * np.array(zooms)
    row = {'case': case,
           'size_xyz': size, 'spacing_xyz_mm': zooms,
           'direction_identity_lps': identity_dir,
           'affine_lps': affine.tolist(),
           'scan_outer_bounds_lps_mm': [outer_lo.tolist(), outer_hi.tolist()],
           'labels': {}}
    for lab in LABELS:
        p = d / 'masks' / f'{lab}.nii.gz'
        if not p.exists():
            row['labels'][lab] = {'missing': True}
            continue
        m = nib.load(str(p))
        if not np.allclose(np.asarray(m.affine), affine, atol=1e-4):
            row['labels'][lab] = {'grid_mismatch': True}
            continue
        arr = np.asarray(m.dataobj) > 0
        row['labels'][lab] = label_stats(arr, affine)
        del arr
    return row


def derive(row):
    """Throat-extension feasibility flags. Only meaningful for identity LPS."""
    out = {}
    if row.get('missing') or not row.get('direction_identity_lps'):
        return out
    lo, hi = row['scan_outer_bounds_lps_mm']
    z_lo, z_hi = lo[2], hi[2]
    out['scan_z_range_mm'] = [z_lo, z_hi]
    for lab in ('oropharynx', 'hypopharynx', 'soft_palate', 'nasopharynx'):
        st = row['labels'].get(lab) or {}
        if st.get('voxels'):
            b = st['bbox_lps_mm']
            out[f'{lab}_z_range_mm'] = [b[0][2], b[1][2]]
            out[f'{lab}_gap_inferior_mm'] = b[0][2] - z_lo
            out[f'{lab}_gap_superior_mm'] = z_hi - b[1][2]
        else:
            out[f'{lab}_z_range_mm'] = None
            out[f'{lab}_gap_inferior_mm'] = None
            out[f'{lab}_gap_superior_mm'] = None
    oro = row['labels'].get('oropharynx') or {}
    out['oropharynx_truncated_inferiorly'] = bool(oro.get('touch_inferior_face'))
    out['hypopharynx_voxels'] = (row['labels'].get('hypopharynx') or {}).get('voxels', 0)
    # distance from current-domain end (nasopharynx bottom) to oropharynx top
    nz = out.get('nasopharynx_z_range_mm')
    oro_z = out.get('oropharynx_z_range_mm')
    if nz and oro_z:
        out['naso_to_oro_interface_gap_mm'] = oro_z[1] - nz[0]
    return out


def main():
    only = sys.argv[1:] or None
    cases = ([c for c in CASES_B + CASES_P if not only or c in only])
    report = {'created': datetime.datetime.now().astimezone().isoformat(),
              'scope': 'T-048 read-only throat coverage audit; no inference, no crop, no mutation',
              'method': 'reuses T-032 inspect_lower_coverage.py (label bbox vs scan bounds + face contact)',
              'cases': {}}
    for c in cases:
        row = audit_case(c)
        row['derived'] = derive(row)
        report['cases'][c] = row
        d = row.get('derived', {})
        oro = row['labels'].get('oropharynx', {})
        print(f"{c:5s} z[{d.get('scan_z_range_mm',[None,None])[0]:8.2f},{d.get('scan_z_range_mm',[None,None])[1]:8.2f}] "
              f"sp_z={row['spacing_xyz_mm'][2]:.3f} oro_vox={oro.get('voxels', 0):7d} "
              f"oro_trunc_inf={str(d.get('oropharynx_truncated_inferiorly')):5s} "
              f"oro_gap_inf={d.get('oropharynx_gap_inferior_mm')} "
              f"hypo_vox={d.get('hypopharynx_voxels')} "
              f"id_dir={row.get('direction_identity_lps')}", flush=True)
    out = Path(__file__).resolve().parent / 'coverage_throat.json'
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print('written:', out)


if __name__ == '__main__':
    main()
