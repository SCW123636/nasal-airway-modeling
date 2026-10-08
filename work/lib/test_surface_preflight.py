"""Unit and label handoff plus native diagnostic interpretation."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
import vtk

from build_reviewed_surface_drafts import write_surface
from ct_case_pipeline import sha256
from prepare_surface_preflight import export_surface, interpret_surface_check
from surface_to_case import parse_vtp_regions
from test_partitioned_surface import cube


class PreflightTests(unittest.TestCase):
    def test_exact_patch_and_unit_handoff(self):
        points, faces = cube()
        labels = np.array(['wall'] * len(faces), dtype=object)
        labels[:3] = ['nostril_L', 'nostril_R', 'nasopharynx_outlet']
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'cube.vtp'
            write_surface(source, points, faces, labels)
            report = export_surface(source, Path(temp) / 'preflight', sha256(source))
            self.assertEqual(set(report['patches']), set(labels))
            self.assertEqual(sum(x['triangles'] for x in report['patches'].values()), len(faces))
            self.assertEqual(report['output_unit'], 'm')
            self.assertTrue(report['all_components_retained'])
            self.assertFalse(report['volume_mesh_generated'])
            self.assertFalse(report['patient_solver_allowed'])

    def test_invalid_and_conflicting_region_arrays_refused(self):
        points, faces = cube()
        for mode in ('conflict', 'numeric', 'length'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                source = Path(temp) / 'cube.vtp'
                write_surface(source, points, faces, ['wall'] * len(faces))
                reader = vtk.vtkXMLPolyDataReader()
                reader.SetFileName(str(source))
                reader.Update()
                poly = reader.GetOutput()
                array = vtk.vtkIntArray() if mode == 'numeric' else vtk.vtkStringArray()
                array.SetName('region')
                for i in range(len(faces) - (mode == 'length')):
                    array.InsertNextValue(1 if mode == 'numeric' else 'outlet')
                poly.GetCellData().AddArray(array)
                writer = vtk.vtkXMLPolyDataWriter()
                writer.SetInputData(poly)
                writer.SetFileName(str(source))
                writer.Write()
                with self.assertRaises(SystemExit):
                    parse_vtp_regions(source)

    def test_zero_exit_cannot_hide_intersections_or_missing_checks(self):
        log = ('Triangles : 12 in 1 region(s)\nwall 12\nSurface has no illegal triangles.\n'
               'Surface is closed. All edges connected to two faces.\n'
               'Surface is self-intersecting at 8 locations.\nEnd\n')
        report = interpret_surface_check(log, 0, {'wall': 12})
        self.assertEqual(report['status'], 'fail')
        self.assertEqual(report['edge_triangle_intersection_hits'], 8)
        for altered in (log.replace('End', ''), log.replace('wall 12', 'wall 11'),
                        log.replace('Surface is self-intersecting at 8 locations.', '')):
            self.assertEqual(interpret_surface_check(altered, 0, {'wall': 12})['status'], 'fail')
        clean = log.replace('Surface is self-intersecting at 8 locations.', 'Surface is not self-intersecting')
        passed = interpret_surface_check(clean, 0, {'wall': 12})
        self.assertEqual(passed['status'], 'native_checks_pass')
        self.assertFalse(passed['meshing_ready'])


if __name__ == '__main__':
    unittest.main()
