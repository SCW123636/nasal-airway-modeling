"""T-047 step 1-2: extended-domain surface for b01 (4-label union + HU cut -> MC -> gates).

Extends the production 3-label flow domain (nasal_cavity_left/right + nasopharynx,
work/lib/batch27_surface.py) with the visible oropharynx — the physical limit of
the scans (T-048 closed loop: 29/29 cases the oropharynx touches the scan
inferior face; nothing below exists in any data).

User rulings 2026-10-16: "fix segmentation position/orientation to the truly
correct position" + "better results over redo cost". T-048 verification proved
position/orientation already correct in 29/29; the actionable improvement is the
domain extent. This script is a T-047 candidate builder: production files are
imported read-only, nothing in work/lib is modified.

Outputs (outputs/T-047/b01_oroext/):
  extended_air_mask.nii.gz   4-label union AND CT<-300 (SimpleITK, CT geometry)
  extended_surface.vtp       marching-cubes surface (production mask_surface)
  extend_surface_report.json voxel accounting + topology + boundary loops
"""
import datetime
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import SimpleITK as sitk

sys.path.insert(0, 'D:/项目/鼻腔建模/work/lib')
from export_candidate_preview import mask_surface, triangle_arrays
from build_reviewed_surface_drafts import write_surface
from partitioned_surface import topology, boundary_loops

CASE = 'b01'
TS_BASE = Path('C:/ts_work')
OUT_DIR = Path(__file__).resolve().parent / 'b01_oroext'
# ITK nifti writer cannot open non-ASCII (Chinese) paths on Windows -> stage in ASCII
STAGING = Path('C:/ts_work/t047_b01_oroext')
HU_MAX = -300.0
PROD_LABELS = ('nasal_cavity_left', 'nasal_cavity_right', 'nasopharynx')
EXT_LABELS = PROD_LABELS + ('oropharynx',)


def loop_report(points, bnd_edges):
    """boundary_loops + per-loop geometry (centroid, bbox, best-fit-plane area)."""
    try:
        loops = boundary_loops(bnd_edges)
    except ValueError as e:
        return {'error': f'boundary loops not closed degree-two: {e}'}
    out = []
    for lp in loops:
        idx = np.asarray(sorted(set(int(v) for v in lp)), dtype=int)
        pts = points[idx]
        cen = pts.mean(axis=0)
        # best-fit plane via PCA; area by 2D shoelace on the two main axes
        _, _, vt = np.linalg.svd(pts - cen, full_matrices=False)
        p2 = (pts - cen) @ vt[:2].T
        # order by angle around centroid for a stable polygon
        ang = np.arctan2(p2[:, 1], p2[:, 0])
        order = np.argsort(ang)
        q = p2[order]
        area = 0.5 * abs(np.dot(q[:, 0], np.roll(q[:, 1], -1)) -
                         np.dot(q[:, 1], np.roll(q[:, 0], -1)))
        out.append({'n_vertices': int(len(idx)),
                    'centroid_mm': [round(float(v), 3) for v in cen],
                    'bbox_mm': [[round(float(v), 3) for v in pts.min(axis=0)],
                                [round(float(v), 3) for v in pts.max(axis=0)]],
                    'area_mm2_approx': round(float(area), 2)})
    out.sort(key=lambda r: r['centroid_mm'][2])
    return {'n_loops': len(out), 'loops': out}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STAGING.mkdir(parents=True, exist_ok=True)
    d = TS_BASE / CASE
    ct = sitk.ReadImage(str(d / 'ct.nii.gz'))
    ct_arr = sitk.GetArrayFromImage(ct)  # (z,y,x)
    per_label = {}
    union_ext = np.zeros(ct_arr.shape, dtype=np.uint8)
    union_prod = np.zeros(ct_arr.shape, dtype=np.uint8)
    for lbl in EXT_LABELS:
        m = sitk.GetArrayFromImage(sitk.ReadImage(str(d / 'masks' / f'{lbl}.nii.gz'))) > 0
        assert m.shape == ct_arr.shape, f'{lbl} shape mismatch'
        per_label[lbl] = int(m.sum())
        union_ext[m] = 1
        if lbl in PROD_LABELS:
            union_prod[m] = 1

    hu = sitk.GetArrayFromImage(sitk.Cast(ct, sitk.sitkFloat32))
    air_ext = (union_ext > 0) & (hu < HU_MAX)
    air_prod = (union_prod > 0) & (hu < HU_MAX)
    sp = ct.GetSpacing()
    vox_vol = float(sp[0] * sp[1] * sp[2])
    n_ext, n_prod = int(air_ext.sum()), int(air_prod.sum())
    assert n_ext > n_prod > 0, 'unexpected voxel accounting'

    mask_img = sitk.GetImageFromArray(air_ext.astype(np.uint8))
    mask_img.CopyInformation(ct)
    sitk.WriteImage(mask_img, str(STAGING / 'extended_air_mask.nii.gz'))

    poly, info = mask_surface(mask_img)
    points, faces = triangle_arrays(poly)
    assert len(points) and len(faces), 'empty surface'
    write_surface(STAGING / 'extended_surface.vtp', points, faces)

    top, bnd = topology(points, faces)
    loops = loop_report(points, bnd) if top['boundary_edges'] else {'n_loops': 0, 'loops': []}

    # z extents of the extended air mask (LPS z from IJK via SimpleITK index->physical)
    zz = np.where(air_ext.any(axis=(1, 2)))[0]
    org = ct.GetOrigin()
    z_inf = float(org[2] + zz.min() * sp[2])
    z_sup = float(org[2] + zz.max() * sp[2])
    ct_z_inf = float(org[2])
    ct_z_sup = float(org[2] + (ct_arr.shape[0] - 1) * sp[2])

    report = {
        'created': datetime.datetime.now().astimezone().isoformat(),
        'case': CASE, 'task': 'T-047 extended-domain surface (oro extension)',
        'labels_union': list(EXT_LABELS), 'hu_max': HU_MAX,
        'per_label_voxels': per_label,
        'air_voxels_extended': n_ext, 'air_voxels_production': n_prod,
        'added_air_voxels': n_ext - n_prod,
        'added_air_volume_mm3': round((n_ext - n_prod) * vox_vol, 1),
        'extended_air_volume_mm3': round(n_ext * vox_vol, 1),
        'production_air_volume_mm3': round(n_prod * vox_vol, 1),
        'mask_z_range_mm': [round(z_inf, 2), round(z_sup, 2)],
        'ct_z_range_mm': [round(ct_z_inf, 2), round(ct_z_sup, 2)],
        'mask_touches_scan_inferior_face': bool(zz.min() == 0),
        'surface_topology': top,
        'boundary_loops': loops,
        'outlet_role': 'engineering_truncation_at_scan_inferior_face',
        'clinical_status': 'generalisation_test_only_no_human_review',
        'notes': 'oropharynx extension reaches scan bottom; opening at the inferior '
                 'face is a truncation, NOT a physiological outlet; downstream '
                 '(hypopharynx+larynx) resistance missing -> delta_p biased low.',
    }
    (STAGING / 'extend_surface_report.json').write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    for f in ('extended_air_mask.nii.gz', 'extended_surface.vtp', 'extend_surface_report.json'):
        shutil.copy2(STAGING / f, OUT_DIR / f)
    print(json.dumps({k: report[k] for k in
                      ('air_voxels_extended', 'air_voxels_production', 'added_air_volume_mm3',
                       'extended_air_volume_mm3', 'mask_touches_scan_inferior_face')},
                     ensure_ascii=False, indent=1))
    print('topology:', {k: top[k] for k in ('boundary_edges', 'nonmanifold_edges',
                                            'duplicate_triangles', 'degenerate_triangles',
                                            'surface_area_mm2', 'signed_volume_mm3',
                                            'triangles', 'vertices')})
    print('loops:', json.dumps(loops, ensure_ascii=False)[:800])
    print('written:', OUT_DIR)


if __name__ == '__main__':
    main()
