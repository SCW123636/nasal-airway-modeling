"""Stage 3: nasal mask -> surface, for the 27-case batch.

The pilot cases got their surfaces through build_reviewed_surface_drafts, which
requires a confirmed human point review. That dependency is exactly what the
batch does not have, so the surface is built directly from the segmentation
masks, using the same production functions the pilot path uses:
export_candidate_preview.mask_surface (marching cubes in voxel space, then the
full LPS affine) and the same HU restriction that keeps bone out of the airway.

Two decisions worth stating because they change the result:

- The three TotalSegmentator labels are UNIONed, then intersected with HU < -300.
  The union alone is what the pilot masks represent; the HU cut removes the
  partial-volume voxels TotalSegmentator includes at the bony airway walls.
  A union without the HU cut gives a visibly thicker, rougher wall.
- The threshold is fixed at -300, the value the pilot pipeline uses. Sweeping
  -300/-350/-400 is a validation task, not something to do silently here.

Output layout matches what auto_opening_pipeline expects:
    <out>/<case>/source_surface.vtp
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import SimpleITK as sitk
import vtk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_candidate_preview import mask_surface, triangle_arrays
from build_reviewed_surface_drafts import write_surface
from partitioned_surface import topology

ROI_LABELS = ('nasal_cavity_left', 'nasal_cavity_right', 'nasopharynx', 'oropharynx')
HU_MAX = -300.0
TS_BASE = Path('C:/ts_work')


def build_case(case, out_root, hu_max=HU_MAX):
    d = TS_BASE / case
    ct_path = d / 'ct.nii.gz'
    mask_dir = d / 'masks'
    if not ct_path.is_file():
        return {'ok': False, 'why': 'ct.nii.gz missing'}
    if not mask_dir.is_dir():
        return {'ok': False, 'why': 'masks dir missing'}

    ct = sitk.ReadImage(str(ct_path))
    ct_arr = sitk.GetArrayFromImage(ct)
    union = np.zeros(ct_arr.shape, dtype=np.uint8)
    per_label = {}
    for r in ROI_LABELS:
        f = mask_dir / f'{r}.nii.gz'
        if not f.is_file():
            return {'ok': False, 'why': f'{r} missing'}
        m = sitk.GetArrayFromImage(sitk.ReadImage(str(f)))
        if m.shape != ct_arr.shape:
            return {'ok': False, 'why': f'{r} shape {m.shape} != ct {ct_arr.shape}'}
        per_label[r] = int((m > 0).sum())
        union[m > 0] = 1

    # HU restriction: voxel centres must be inside the union mask AND air.
    hu = sitk.GetArrayFromImage(sitk.Cast(ct, sitk.sitkFloat32))
    air = (union > 0) & (hu < hu_max)
    voxels = int(air.sum())
    if voxels == 0:
        return {'ok': False, 'why': 'empty after HU cut',
                'union_voxels': int(union.sum()), 'per_label': per_label}

    img = sitk.GetImageFromArray(air.astype(np.uint8))
    img.CopyInformation(ct)
    poly, info = mask_surface(img)
    points, faces = triangle_arrays(poly)
    if not len(points) or not len(faces):
        return {'ok': False, 'why': 'empty surface', 'union_voxels': int(union.sum())}

    top, _ = topology(points, faces)
    out_dir = Path(out_root) / case
    out_dir.mkdir(parents=True, exist_ok=True)
    # The air mask is written out because stage 5 needs it: the extended-domain
    # outlet is an engineering truncation whose plane is derived from the mask's
    # bottom voxel-centre plane, not from an anatomical landmark.
    sitk.WriteImage(img, str(out_dir / 'air_mask.nii.gz'), True)
    write_surface(out_dir / 'source_surface.vtp', points, faces)
    return {'ok': True, 'union_voxels': int(union.sum()), 'air_voxels': voxels,
            'air_mask': str(out_dir / 'air_mask.nii.gz'),
            'hu_max': hu_max, 'per_label_voxels': per_label,
            'points': int(len(points)), 'triangles': int(len(faces)),
            'surface_qc': top, 'path': str(out_dir / 'source_surface.vtp')}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cases', nargs='+', default=None)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--hu-max', type=float, default=HU_MAX)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cases = args.cases or [f'b{i:02d}' for i in range(1, 28)]
    rows = {}
    for case in cases:
        try:
            r = build_case(case, args.out, args.hu_max)
        except Exception as exc:
            r = {'ok': False, 'why': f'{type(exc).__name__}: {exc}'}
        rows[case] = r
        if r['ok']:
            print(f"{case}: OK  air={r['air_voxels']}  pts={r['points']}  tri={r['triangles']}"
                  f"  boundary={r['surface_qc'].get('boundary_edges')}", flush=True)
        else:
            print(f"{case}: FAIL  {r['why']}", flush=True)
    ok = sum(1 for v in rows.values() if v['ok'])
    (args.out / 'surface_build.json').write_text(
        json.dumps({'schema': 'batch27_surface/v1', 'hu_max': args.hu_max,
                    'ok': ok, 'total': len(rows), 'cases': rows},
                   indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'\nbuilt {ok}/{len(rows)}; written {args.out / "surface_build.json"}')


if __name__ == '__main__':
    main()