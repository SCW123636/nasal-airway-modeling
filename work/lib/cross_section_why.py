"""Why does the cross-section area come out None?

cross_section_scan.py printed only a dash when the area was unavailable, so a
wrong criterion and a broken measurement looked identical. This prints the
actual reason for a handful of shifts on one case.
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
from cross_section_scan import cross_section, plane_basis, SRC
from connectivity_opened_surface import OPENINGS


def main():
    work = Path(__file__).resolve().parents[1]
    mgr = CaseManager(Path('C:/ts_work/project_cases'))
    store = MedicalReviewStore(mgr, work / '06_auto_landmarks')
    try:
        for case in ('p2', 'p0'):
            config, _ = load_adopted(store, case)
            reader = vtk.vtkXMLPolyDataReader()
            reader.SetFileName(str(SRC / case / 'source_surface.vtp'))
            reader.Update()
            points, faces = triangle_arrays(reader.GetOutput())
            print('=' * 30, case)
            for name in OPENINGS:
                spec = config['planes_lps'][name]
                n, _, _ = plane_basis(spec['normal_lps'])
                o = np.asarray(spec['point_lps_mm'], float)
                for d in (-6, 0, 6):
                    moved = dict(spec)
                    moved['point_lps_mm'] = (o + d * n).tolist()
                    area, info = cross_section(points, faces, moved)
                    print(f'  {name:18s} {d:+3d}  {info if area is None else f"area={area:.1f} mm2"}')
    finally:
        mgr.pool.shutdown(wait=True)


if __name__ == '__main__':
    main()