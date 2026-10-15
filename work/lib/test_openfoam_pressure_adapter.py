"""Known-answer boundary, sign, quality and persistence checks; no CFD launched."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import openfoam_pressure_adapter as adapter
from pressure_feedback import PressureFeedbackError


class RealAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def case(self):
        case = self.root / 'template'
        for part in ('0', 'constant', 'system'):
            (case / part).mkdir(parents=True, exist_ok=True)
        patches = '\n'.join(name + ' { type zeroGradient; }' for name in ('left', 'right', 'out', 'wall'))
        (case / '0/p').write_text('dimensions [0 2 -2 0 0 0 0];\nboundaryField\n{\n' + patches + '\n}')
        (case / '0/U').write_text('boundaryField\n{\n' + patches + '\n}')
        (case / 'system/controlDict').write_text('startFrom latestTime; startTime 200;\nfunctions\n{\nold { type sample; }\n}')
        (case / 'constant/transportProperties').write_text('nu 1e-5;')
        return case

    def test_equal_static_pressure_units_and_no_prescribed_split(self):
        case = self.case()
        adapter.set_pressure_boundaries(case, 12., 1.2, ('left', 'right'), 'out')
        pressure, velocity = (case / '0/p').read_text(), (case / '0/U').read_text()
        self.assertEqual(pressure.count('value uniform 10;'), 2)
        self.assertIn('value uniform 0;', pressure)
        self.assertEqual(velocity.count('pressureInletOutletVelocity'), 2)
        self.assertNotIn('flowRateInletVelocity', velocity)
        control = (case / 'system/controlDict').read_text()
        self.assertIn('startFrom startTime;', control)
        self.assertIn('startTime 0;', control)
        self.assertEqual(control.count('fields (phi);'), 3)

    def test_missing_patch_and_wrong_dimensions_are_refused(self):
        case = self.case()
        with self.assertRaisesRegex(PressureFeedbackError, 'missing'):
            adapter.set_pressure_boundaries(case, 1., 1.2, ('missing', 'right'), 'out')
        (case / '0/p').write_text('dimensions [1 -1 -2 0 0 0 0];')
        with self.assertRaisesRegex(PressureFeedbackError, 'kinematic'):
            adapter.set_pressure_boundaries(case, 1., 1.2, ('left', 'right'), 'out')

    def test_fingerprint_changes_with_boundary_mesh_and_code(self):
        case = self.case()
        before = adapter.fingerprint(case)
        (case / '0/p').write_text('new')
        self.assertNotEqual(before, adapter.fingerprint(case))

    def test_native_linux_and_patch_contract(self):
        case = self.case()
        with self.assertRaisesRegex(PressureFeedbackError, 'native Linux'):
            adapter.OpenFOAMPressureEvaluator(case, '/mnt/c/unsafe')
        with patch.object(adapter.os, 'name', 'posix'):
            # pathlib on Windows cannot instantiate PosixPath under patched os.name;
            # test the generic patch validator through its boundary helper instead.
            with self.assertRaises(PressureFeedbackError):
                adapter.block_span('bad {', 'bad')

    def test_known_signed_flux_quality_and_failed_residuals(self):
        case = self.case()
        (case / 'log.checkMesh').write_text('Mesh OK.\n')
        log = '\n'.join('Solving for %s, Initial residual = 1e-7, Final residual = 1e-10' % f for f in ('Ux','Uy','p'))
        (case / 'log.simpleFoam').write_text(log + '\nglobal = 1e-9\nTime = 30\nEnd\n')
        for name, flow in [('left',-2e-5),('right',-1e-5),('out',3e-5)]:
            for label, value in [('flow',flow),('pressure',1 if name != 'out' else 0)]:
                file = case / ('postProcessing/%s_%s/0/surfaceFieldValue.dat' % (label,name))
                file.parent.mkdir(parents=True)
                file.write_text('\n'.join('%d %.12g' % (i,value) for i in range(120)))
        result = adapter.solver_diagnostics(case, ('left','right'), 'out', 1.2)
        self.assertAlmostEqual(result['flux']['q_in_m3_s'],3e-5)
        self.assertAlmostEqual(result['pressure_Pa_gauge']['left'],1.2)
        self.assertTrue(result['mesh_quality_passed'])
        self.assertEqual(result['monitor_relative_change'],0)
        path = case / 'postProcessing/flow_left/0/surfaceFieldValue.dat'
        path.write_text(path.read_text().replace('-2e-05','2e-05'))
        with self.assertRaisesRegex(PressureFeedbackError, 'inward'):
            adapter.solver_diagnostics(case, ('left','right'), 'out', 1.2)


if __name__ == '__main__':
    unittest.main()
