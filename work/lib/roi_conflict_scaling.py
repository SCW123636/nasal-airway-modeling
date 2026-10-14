"""Why does ROI padding not converge? Measure conflict count vs padding.

Hypothesis H1 (tight box): the deleted wall only pokes a fraction of a mm past
the ROI face, so a small pad clears it.
Hypothesis H2 (unbounded lobe): the deleted region is not box-shaped, so growing
the ROI just pulls in more deleted wall that again straddles the new face. The
conflict count plateaus instead of falling to zero.

This measures both: conflict count, per-axis crossing side, and how far the
negative-side component extends beyond the ROI face.
"""
import sys
from pathlib import Path

import numpy as np
import vtk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_reviewed_surface_drafts import load_adopted
from ct_case_pipeline import CaseManager, read_json
from medical_review import MedicalReviewStore
from export_candidate_preview import triangle_arrays

SRC = Path('C:/ts_work/reviewed_surface_drafts_20261008_r3')
PADS = (0.0, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0)
TOL = 1e-7


def analyse(points, faces, spec, pad):
    roi = spec['roi_lps_mm']
    low = np.asarray(roi['min'], float) - pad
    high = np.asarray(roi['max'], float) + pad
    normal = np.asarray(spec['normal_lps'], float)
    normal = normal / np.linalg.norm(normal)
    origin = np.asarray(spec['point_lps_mm'], float)
    kept = normal if spec['keep_positive'] else -normal
    signed = (points - origin) @ kept
    signed[np.abs(signed) <= TOL] = 0
    xyz = points[faces]
    overlap = ((xyz.max(axis=1) >= low) & (xyz.min(axis=1) <= high)).all(axis=1)
    inside = ((xyz >= low) & (xyz <= high)).all(axis=(1, 2))
    negative = np.any(signed[faces] < 0, axis=1)
    conflict = overlap & ~inside & negative
    # how far does deleted wall reach past each ROI face, ignoring the ROI box?
    neg_pts = points[signed < 0]
    out = {}
    if len(neg_pts):
        out['neg_bbox_min'] = neg_pts.min(axis=0)
        out['neg_bbox_max'] = neg_pts.max(axis=0)
    n = int(conflict.sum())
    sides = np.zeros(3, int)
    if n:
        c = xyz[conflict]
        sides = np.array([int((c.min(axis=(0, 1))[k] < low[k]) + (c.max(axis=(0, 1))[k] > high[k]))
                          for k in range(3)])
    return n, sides, out


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
            print('=' * 22, case, 'tris', len(faces))
            for name in ('nostril_L', 'nostril_R', 'nasopharynx_outlet'):
                spec = config['planes_lps'][name]
                row = []
                neg_extent = None
                for pad in PADS:
                    n, sides, out = analyse(points, faces, spec, pad)
                    row.append((pad, n, tuple(sides)))
                    if pad == 0.0:
                        neg_extent = out
                print(f'  {name}:')
                for pad, n, sides in row:
                    print(f'    pad {pad:6.2f} mm  conflict {n:6d}  sides(min,max) {sides}')
                if neg_extent:
                    roi = np.asarray(spec['roi_lps_mm']['min'], float), np.asarray(spec['roi_lps_mm']['max'], float)
                    dn = roi[0] - neg_extent['neg_bbox_min']
                    dp = neg_extent['neg_bbox_max'] - roi[1]
                    print('    deleted-side wall extent beyond ROI (mm): below',
                          np.round(np.maximum(dn, 0), 1), ' above', np.round(np.maximum(dp, 0), 1))
    finally:
        mgr.pool.shutdown(wait=True)


if __name__ == '__main__':
    main()