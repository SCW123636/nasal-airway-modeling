"""Synthetic tests for circular inlet radius and mesh quality gating."""
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import phantom_validation as phantom
import phantom_developed_validation as developed

_path = Path(__file__).resolve().parents[1]/'07_cfd_pipeline'/'solver'/'run_openfoam_case.py'
_spec = importlib.util.spec_from_file_location('openfoam_executor_test', _path)
executor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(executor)


class SolverBoundaryTests(unittest.TestCase):
    def disk(self, root):
        tube = root/'tube.stl'
        phantom.generate_tube_stl(tube)
        target = root/'constant'/'triSurface'/'inlet.stl'
        target.parent.mkdir(parents=True)
        text = tube.read_text(encoding='ascii').split('endsolid inlet')[0]+'endsolid inlet\n'
        import re
        text = re.sub(r'vertex (\S+) (\S+) (\S+)',
                      lambda m:'vertex '+ ' '.join(str(float(v)*.001) for v in m.groups()), text)
        target.write_text(text,encoding='ascii')

    def test_radius_comes_from_boundary_not_interior_face_centroids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.disk(root)
            center,radius,normal=executor.circular_source_geometry(root,'inlet',(1e-5,0,1))
            self.assertAlmostEqual(radius,.002)
            self.assertLess(math.dist(center,(0,0,0)),1e-15)
            self.assertEqual(normal,(0.,0.,1.))

    def test_profile_preserves_target_flow_and_outer_faces_remain_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.disk(root);(root/'0').mkdir()
            (root/'0/U').write_text('boundaryField { inlet { type flowRateInletVelocity; volumetricFlowRate constant 0.00025; } }',encoding='ascii')
            centers=[(.0005,0,0),(-.0005,0,0),(.0018,0,0),(-.0018,0,0)]
            vectors=[(0,0,-1e-6)]*4
            manifest={'boundary':{'per_inlet_flow_m3_s':{'inlet':.00025}}}
            with mock.patch.object(executor,'patch_faces',return_value=(centers,vectors)):
                record=executor.set_parabolic_inlet(root,manifest)['inlet']
            import re
            values=re.findall(r'\(([-+0-9.eE]+) ([-+0-9.eE]+) ([-+0-9.eE]+)\)',(root/'0/U').read_text())
            speeds=[float(v[2]) for v in values]
            self.assertTrue(all(speed>0 for speed in speeds))
            self.assertAlmostEqual(sum(speeds)*1e-6,.00025)
            self.assertEqual(record['radius_source'],'source_STL_boundary_vertices')

    def test_mesh_failure_is_detected_even_when_command_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'log.checkMesh').write_text('Failed 1 mesh checks.\nEnd\n')
            self.assertFalse(executor.mesh_quality(root)['passed'])
            (root/'log.checkMesh').write_text('Mesh OK.\nEnd\n')
            self.assertTrue(executor.mesh_quality(root)['passed'])
            (root/'log.checkMesh').write_text('End\n')
            self.assertFalse(executor.mesh_quality(root)['passed'])

    def test_failed_mesh_blocks_solver_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'log.checkMesh').write_text('Failed 1 mesh checks.\nEnd\n')
            with mock.patch.object(executor,'check_case_complete'),mock.patch.object(executor,'is_sst',return_value=False),mock.patch.object(executor,'execute') as run:
                with self.assertRaisesRegex(RuntimeError,'Mesh quality did not pass'):
                    executor.main(['--case',str(root),'--steps','simpleFoam'])
                run.assert_not_called()
            manifest=json.loads((root/'run_manifest.json').read_text())
            self.assertEqual(manifest['execution_status'],'failed')
            self.assertFalse(manifest['engineering_acceptance'])

    def test_diagnostic_override_is_not_allowed_for_other_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'case_manifest.json').write_text(json.dumps({'surface':{'source_file':'patient.stl'}}))
            with mock.patch.object(executor,'check_case_complete'),mock.patch.object(executor,'is_sst',return_value=False),mock.patch.object(executor,'execute') as run:
                with self.assertRaises(SystemExit):
                    executor.main(['--case',str(root),'--steps','simpleFoam','--allow-failed-mesh-for-diagnostic'])
                run.assert_not_called()

    def test_long_tube_configuration_does_not_change_baseline_globals(self):
        length=phantom.L_MM
        with developed.configured():
            self.assertEqual(phantom.L_MM,160)
        self.assertEqual(phantom.L_MM,length)


if __name__=='__main__':
    unittest.main()
