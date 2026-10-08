"""Scope proposals preserve point review and remain separate from approval."""
import copy
from pathlib import Path
import tempfile
import unittest

import numpy as np
import vtk

from build_reviewed_surface_drafts import write_surface
from propose_surface_scope import propose_roi
from test_partitioned_surface import cube, plane


class ScopeProposalTests(unittest.TestCase):
    def test_unrelated_components_not_used_to_expand_roi(self):
        vertices, faces = cube()
        points = np.vstack((vertices, vertices + [100, 0, 0]))
        triangles = np.vstack((faces, faces + len(vertices)))
        control = plane([0, 0, 2], [0, 0, 1])
        control['status'] = 'confirmed'
        before = copy.deepcopy(control)
        proposed, evidence = propose_roi(points, triangles, control)
        self.assertEqual(control, before)
        self.assertEqual(proposed['point_lps_mm'], before['point_lps_mm'])
        self.assertEqual(proposed['normal_lps'], before['normal_lps'])
        self.assertLess(proposed['roi_lps_mm']['max'][0], 100)
        self.assertEqual(proposed['status'], 'proposed_scope')
        self.assertEqual(proposed['point_localization_status'], 'confirmed')
        self.assertEqual(evidence['selected_negative_components'], 1)
        self.assertFalse(evidence['patient_solver_allowed'])

    def test_invalid_controls_and_no_seed_refused(self):
        vertices, faces = cube()
        for normal in ([0, 0, 0], [np.nan, 0, 1]):
            with self.assertRaisesRegex(ValueError, 'Invalid'):
                propose_roi(vertices, faces, plane([0, 0, 2], normal))
        with self.assertRaisesRegex(ValueError, 'No negative'):
            propose_roi(vertices, faces, plane([0, 0, -1], [0, 0, 1]))
        with self.assertRaisesRegex(ValueError, 'Padding'):
            propose_roi(vertices, faces, plane([0, 0, 2], [0, 0, 1]), padding_mm=-1)

    def test_patch_labels_round_trip_and_length_contract(self):
        vertices, faces = cube()
        labels = ['wall'] * 8 + ['nostril_L', 'nostril_R', 'nasopharynx_outlet', 'wall']
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'surface.vtp'
            write_surface(path, vertices, faces, labels)
            reader = vtk.vtkXMLPolyDataReader()
            reader.SetFileName(str(path))
            reader.Update()
            restored = reader.GetOutput().GetCellData().GetAbstractArray('boundary_patch')
            self.assertEqual([restored.GetValue(i) for i in range(len(labels))], labels)
            with self.assertRaisesRegex(ValueError, 'per triangle'):
                write_surface(path, vertices, faces, labels[:-1])


if __name__ == '__main__':
    unittest.main()
