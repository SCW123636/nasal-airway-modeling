"""Locate the p0 outlet failure by bisecting the clip order, using production code.

No hand-rolled clip here: every run calls partitioned_surface.clip_and_cap so the
failure is the real one, not a re-implementation that might drift.
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
from partitioned_surface import clip_and_cap, topology
from connectivity_opened_surface import flood_mask

SRC = Path('C:/ts_work/reviewed_surface_drafts_20261008_r3')
OPENINGS = ('nostril_L', 'nostril_R', 'nasopharynx_outlet')


def run(points, faces, planes, selectors, order):
    try:
        p, f, patches, qc = clip_and_cap(points, faces, {k: planes[k] for k in order},
                                         selectors={k: selectors[k] for k in order})
        return 'pass', qc.get('technical_qc', qc)
    except ValueError as exc:
        return 'fail: ' + str(exc), None


def main():
    work = Path(__file__).resolve().parents[1]
    mgr = CaseManager(Path('C:/ts_work/project_cases'))
    store = MedicalReviewStore(mgr, work / '06_auto_landmarks')
    try:
        for case in ('p0', 'p1'):
            config, _ = load_adopted(store, case)
            reader = vtk.vtkXMLPolyDataReader()
            reader.SetFileName(str(SRC / case / 'source_surface.vtp'))
            reader.Update()
            points, faces = triangle_arrays(reader.GetOutput())
            planes = {k: config['planes_lps'][k] for k in OPENINGS}
            selectors = {k: flood_mask(points, faces, planes[k])[0] for k in OPENINGS}
            print('=' * 16, case)
            for order in (('nasopharynx_outlet',), ('nostril_L', 'nasopharynx_outlet'),
                          ('nostril_R', 'nasopharynx_outlet'),
                          ('nostril_L', 'nostril_R', 'nasopharynx_outlet')):
                status, qc = run(points, faces, planes, selectors, order)
                extra = ''
                if qc:
                    extra = (f"  caps={ {k: v['loops'] for k, v in qc['caps'].items()} }"
                             if 'caps' in qc else '')
                print(f"   {'+'.join(order):45s} {status}{extra}")
    finally:
        mgr.pool.shutdown(wait=True)


if __name__ == '__main__':
    main()