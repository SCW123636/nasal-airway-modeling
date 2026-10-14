"""Synthetic tests for circular inlet radius and mesh quality gating."""
import contextlib
import importlib.util
import io
import json
import math
import re
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

_mesh_path = Path(__file__).resolve().parents[1]/'07_cfd_pipeline'/'solver'/'mesh_cache.py'
_mesh_spec = importlib.util.spec_from_file_location('mesh_cache_test', _mesh_path)
mesh_cache = importlib.util.module_from_spec(_mesh_spec)
_mesh_spec.loader.exec_module(mesh_cache)


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


class SolverEngineeringTests(unittest.TestCase):
    def _run(self, root, argv):
        with mock.patch.object(executor, 'check_case_complete'), \
             mock.patch.object(executor, 'is_sst', return_value=False), \
             mock.patch.object(executor, 'mesh_quality', return_value={'passed': True, 'failed_checks': None, 'log': 'log.checkMesh'}), \
             mock.patch.object(executor, 'execute', side_effect=lambda cmd, case, env, log: {'command': cmd, 'exit_code': 0, 'elapsed_seconds': 0.0, 'log': str(case / log)}):
            return executor.main(argv)

    def test_status_file_streams_to_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status = root / 'run_status.json'
            self._run(root, ['--case', str(root), '--steps', 'simpleFoam'])
            self.assertTrue(status.is_file())
            payload = json.loads(status.read_text())
            self.assertEqual(payload['status'], 'completed')
            self.assertEqual(payload['total_steps'], 1)
            self.assertEqual(payload['current_step_index'], 1)

    def test_parallel_falls_back_to_serial_when_mpirun_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(executor.shutil, 'which', return_value=None):
                self._run(root, ['--case', str(root), '--steps', 'simpleFoam', '--parallel', '4'])
            manifest = json.loads((root / 'run_manifest.json').read_text())
            self.assertFalse(manifest['parallel'])

    def test_archive_before_run_preserves_mesh_cache_and_initial_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'mesh_cache.json').write_text('{"keep": true}')
            (root / 'run_manifest.json').write_text('{"old": true}')
            (root / '500').mkdir()
            (root / '500' / 'U').write_text('stale field')
            (root / '0').mkdir()
            (root / '0' / 'U').write_text('boundary conditions')
            executor._archive_before_run(root)
            # the cross-run mesh record must survive archiving, or --skip-mesh-if-cached breaks
            self.assertTrue((root / 'mesh_cache.json').is_file())
            self.assertFalse((root / 'run_manifest.json').exists())
            self.assertFalse((root / '500').exists())
            self.assertTrue((root / '0' / 'U').is_file())

    def test_skip_mesh_if_cached_drops_blockmesh_and_snappy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'constant' / 'triSurface').mkdir(parents=True)
            (root / 'constant' / 'triSurface' / 'nasal.stl').write_text(
                "solid s\n facet normal 0 0 1\n  outer loop\n"
                "   vertex 0 0 0\n   vertex 1 0 0\n   vertex 0 1 0\n  endloop\n endfacet\nendsolid s\n", encoding='ascii')
            for name in ('blockMeshDict', 'snappyHexMeshDict', 'fvSchemes', 'fvSolution', 'controlDict'):
                (root / 'system').mkdir(parents=True, exist_ok=True)
                (root / 'system' / name).write_text(
                    "FoamFile { version 2.0; format ascii; class dictionary; object %s; }\nkey value;\n" % name, encoding='ascii')
            (root / 'constant' / 'polyMesh').mkdir(parents=True)
            for name in ('points', 'faces', 'owner', 'neighbour', 'boundary'):
                (root / 'constant' / 'polyMesh' / name).write_text('mesh %s\n' % name, encoding='ascii')
            (root / 'log.checkMesh').write_text('Mesh OK.\n', encoding='ascii')
            identity = mesh_cache.detect_backend_identity()
            sig = mesh_cache.mesh_inputs_signature(root, identity)
            rec = mesh_cache.record_mesh(root, sig, 'run-1',
                                        check_result={'returncode': 0, 'output': 'Mesh OK.\n', 'timed_out': False},
                                        completed_steps=[{'name': 'blockMesh', 'returncode': 0, 'timed_out': False},
                                                        {'name': 'snappyHexMesh', 'returncode': 0, 'timed_out': False},
                                                        {'name': 'checkMesh', 'returncode': 0, 'timed_out': False}])
            self.assertTrue(rec['recorded'])
            self._run(root, ['--case', str(root), '--steps', 'blockMesh,snappyHexMesh,checkMesh,simpleFoam', '--skip-mesh-if-cached'])
            manifest = json.loads((root / 'run_manifest.json').read_text())
            names = [s['command'][0] for s in manifest['steps']]
            self.assertNotIn('blockMesh', names)
            self.assertNotIn('snappyHexMesh', names)
            self.assertTrue(manifest['mesh_skipped'])

    def test_parallel_preflight_calls_real_shutil_which_without_crashing(self):
        """Regression: shutil.which has no `env` parameter.

        The mock in test_parallel_falls_back_to_serial_when_mpirun_missing accepts any
        keyword, so it never caught `shutil.which(t, env=environment)` raising TypeError
        on every real --parallel run. This test calls the real shutil.which.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rc = self._run(root, ['--case', str(root), '--steps', 'simpleFoam', '--parallel', '4'])
            self.assertEqual(rc, 0)
            manifest = json.loads((root / 'run_manifest.json').read_text())
            self.assertIsInstance(manifest['parallel'], bool)

    def test_parallel_expands_simplefoam_into_decompose_solve_reconstruct(self):
        commands = {'simpleFoam': ['simpleFoam'], 'checkMesh': ['checkMesh']}
        seq = executor._effective_sequence('simpleFoam', commands, True, 4)
        names = [name for name, _ in seq]
        self.assertEqual(names, ['decomposePar', 'simpleFoam', 'reconstructPar'])
        self.assertEqual(seq[0][1], ['decomposePar', '-force', '-time', '0'])
        self.assertEqual(seq[1][1], ['mpirun', '-np', '4', 'simpleFoam', '-parallel'])
        self.assertEqual(seq[2][1], ['reconstructPar', '-latestTime'])
        # mesh tooling stays serial: decomposing it would corrupt the mesh
        self.assertEqual([n for n, _ in executor._effective_sequence('checkMesh', commands, True, 4)],
                         ['checkMesh'])
        # serial mode must not silently grow MPI steps
        self.assertEqual([n for n, _ in executor._effective_sequence('simpleFoam', commands, False, 0)],
                         ['simpleFoam'])

    def test_parallel_expands_snappy_with_constant_reconstruction(self):
        commands = {'snappyHexMesh': ['snappyHexMesh', '-overwrite']}
        seq = executor._effective_sequence('snappyHexMesh', commands, True, 8)
        self.assertEqual([n for n, _ in seq], ['decomposePar', 'snappyHexMesh', 'reconstructPar'])
        self.assertEqual(seq[0][1], ['decomposePar', '-force', '-noFields'])
        self.assertEqual(seq[1][1], ['mpirun', '-np', '8', 'snappyHexMesh', '-parallel', '-overwrite'])
        self.assertEqual(seq[2][1], ['reconstructPar', '-constant', '-noFields', '-time', '0'])

    def test_mesh_cache_is_recorded_after_a_blockmesh_only_run(self):
        """Regression: record_mesh requires the step sequence to END with checkMesh.

        The executor used to hand it the full step list, which ends with foamToVTK
        (or reconstructPar in parallel mode). That made every record attempt fail
        silently with "前序步骤失败或检查记录缺失", so --skip-mesh-if-cached never hit
        on blockMesh-only cases -- the feature was dead on arrival.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'system').mkdir()
            for name in ('blockMeshDict', 'fvSchemes', 'fvSolution', 'controlDict'):
                (root / 'system' / name).write_text(
                    "FoamFile { version 2.0; format ascii; class dictionary; object %s; }\nkey value;\n" % name,
                    encoding='ascii')
            (root / 'constant' / 'polyMesh').mkdir(parents=True)
            for name in ('points', 'faces', 'owner', 'neighbour', 'boundary'):
                (root / 'constant' / 'polyMesh' / name).write_text('mesh %s\n' % name, encoding='ascii')
            (root / 'log.checkMesh').write_text('Mesh OK.\n', encoding='ascii')
            self._run(root, ['--case', str(root), '--steps', 'blockMesh,checkMesh,simpleFoam,foamToVTK'])
            self.assertTrue((root / 'mesh_cache.json').is_file(),
                            'blockMesh-only case must still register a reusable mesh')
            manifest = json.loads((root / 'run_manifest.json').read_text())
            self.assertTrue(manifest['mesh_cache']['recorded'])
            # and the next run must actually skip mesh generation
            self._run(root, ['--case', str(root), '--steps', 'blockMesh,checkMesh,simpleFoam,foamToVTK',
                             '--skip-mesh-if-cached'])
            names = [s['command'][0] for s in
                     json.loads((root / 'run_manifest.json').read_text())['steps']]
            self.assertNotIn('blockMesh', names)

    def test_decompose_par_dict_avoids_scotch_and_declares_n_vector(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'system').mkdir()
            executor._ensure_decompose_par_dict(root, 4)
            text = (root / 'system' / 'decomposeParDict').read_text()
            # scotch aborts on this build (dummy scotchDecomp stub)
            self.assertIn('method hierarchical;', text)
            self.assertNotIn('scotch', text)
            # hierarchical reads the vector entry n, not just numberOfSubdomains
            self.assertIn('n (4 1 1);', text)
            self.assertIn('numberOfSubdomains 4;', text)

    def test_existing_scotch_or_n_vectorless_dict_is_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'system').mkdir()
            target = root / 'system' / 'decomposeParDict'
            target.write_text(
                'FoamFile { version 2.0; format ascii; class dictionary; '
                'object decomposeParDict; }\nnumberOfSubdomains 2;\nmethod scotch;\n'
                'distributed no;\nroots ();\n', encoding='ascii')
            executor._ensure_decompose_par_dict(root, 8)
            text = target.read_text()
            self.assertNotIn('scotch', text)
            self.assertIn('method hierarchical;', text)
            self.assertIn('n (8 1 1);', text)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'system').mkdir()
            target = root / 'system' / 'decomposeParDict'
            target.write_text('numberOfSubdomains 2;\nmethod hierarchical;\n', encoding='ascii')
            executor._ensure_decompose_par_dict(root, 5)
            self.assertIn('n (5 1 1);', target.read_text())

    def test_untouched_decompose_par_dict_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'system').mkdir()
            target = root / 'system' / 'decomposeParDict'
            original = 'numberOfSubdomains 6;\nmethod simple;\ndistributed no;\nroots ();\n'
            target.write_text(original, encoding='ascii')
            executor._ensure_decompose_par_dict(root, 4)
            self.assertEqual(target.read_text(), original)


class ContractGateTests(unittest.TestCase):
    """T-003 R10: the contract gate must refuse unsanctioned configs and stay
    byte-for-byte compatible when --config is absent. Configs are synthesized in
    temp dirs; the 8 catalog configs are never touched.
    """

    def _write_config(self, root, payload):
        path = root / 'contract_config.json'
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return str(path)

    def _authorized_config(self):
        """A synthetic, fully execution-ready idealized config (no patient review)."""
        return {
            "schema": "nasal_cfd_config/v1",
            "config_id": "synthetic_authorized_idealized",
            "physics": {"flow_regime": "incompressible", "time_mode": "steady",
                        "rho_kg_m3": 1.2, "mu_Pa_s": 1.81e-5, "turbulence_model": "laminar"},
            "boundary_conditions": {
                "mode": "total_flow",
                "total_inspiratory_flow_m3_s": 2.5e-4,
                "flow_split": {"policy": "imposed_equal_split_baseline",
                               "left_fraction": 0.5, "right_fraction": 0.5,
                               "interpretation": "imposed_baseline_not_patient_split"},
                "nostril_pressure": None,
                "nasopharynx_pressure": {"value": 0.0, "unit": "Pa", "quantity": "static", "reference": "gauge"},
                "static_pressure_difference_Pa": None,
                "direction_policy": "inspiration_nostrils_to_nasopharynx",
                "walls": "rigid_no_slip"},
            "turbulence": {"inlet_intensity_fraction": None, "length_scale_Dh_fraction": None,
                           "low_speed_threshold_m_s": None, "low_speed_threshold_basis": None,
                           "definition": None, "report_status": "not_applicable"},
            "mesh": {"level": "medium", "bulk_target_mm": 0.4, "local_initial_target_mm": 0.25,
                     "minimum_cells_across_gap": 6,
                     "local_resolution_rule": "h <= min(local_initial_target_mm, measured_gap_mm/6)",
                     "prism_layers": None},
            "geometry": {"kind": "idealized", "case_id": None, "source_file": "phantom_tube.stl",
                         "sha256": None, "units": "mm", "solver_units": "m", "scale_to_m": 0.001,
                         "coordinate_system": "LPS", "review": None},
            "solver_adapter": {"status": "implemented_and_verified", "name": None, "version": None,
                               "desired_strategy": None, "flow_target_role": None, "strategy_description": None},
            "engineering_screen": {"maximum_mass_imbalance_fraction": 0.005,
                                   "maximum_monitor_relative_change": 0.005,
                                   "target_residual_max": 1e-5, "medium_to_fine_change_screen_fraction": 0.05},
            "notes": ["synthetic authorized config for T-003 contract-gate tests"]}

    def _unsanctioned_config(self):
        cfg = self._authorized_config()
        cfg["config_id"] = "synthetic_unsanctioned"
        # Readiness issue -> execution_allowed False (reason surfaces in warnings).
        cfg["solver_adapter"]["status"] = "not_implemented"
        return cfg

    def test_no_config_behaves_identically_to_baseline(self):
        """No --config: nothing is refused, steps run, manifest carries the stub."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(executor, 'check_case_complete'), \
                 mock.patch.object(executor, 'is_sst', return_value=False), \
                 mock.patch.object(executor, 'mesh_quality', return_value={'passed': True}), \
                 mock.patch.object(executor, 'execute', side_effect=lambda cmd, case, env, log:
                                   {'command': cmd, 'exit_code': 0, 'elapsed_seconds': 0.0, 'log': str(case / log)}) as run:
                rc = executor.main(['--case', str(root), '--steps', 'simpleFoam'])
            self.assertEqual(rc, 0)
            run.assert_called()
            manifest = json.loads((root / 'run_manifest.json').read_text())
            self.assertEqual(manifest['contract'], {"config_id": None, "checked": False})
            self.assertFalse(manifest['engineering_acceptance'])

    def test_unsanctioned_without_force_is_refused_naming_reason(self):
        """execution_allowed=False and no --force -> non-zero exit, named cause, no step run."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_path = self._write_config(root, self._unsanctioned_config())
            err = io.StringIO()
            with contextlib.redirect_stderr(err), \
                 mock.patch.object(executor, 'check_case_complete') as cc, \
                 mock.patch.object(executor, 'execute') as run:
                rc = executor.main(['--case', str(root), '--config', cfg_path, '--steps', 'simpleFoam'])
            self.assertNotEqual(rc, 0)
            run.assert_not_called()
            cc.assert_not_called()
            text = err.getvalue()
            self.assertIn('refusing to run an unsanctioned configuration', text)
            self.assertIn('solver adapter has not been implemented and verified', text)

    def test_unsanctioned_with_force_is_allowed_and_logged(self):
        """execution_allowed=False + --force-unsanctioned -> runs, contract.forced recorded."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_path = self._write_config(root, self._unsanctioned_config())
            with contextlib.redirect_stderr(io.StringIO()), \
                 mock.patch.object(executor, 'check_case_complete'), \
                 mock.patch.object(executor, 'is_sst', return_value=False), \
                 mock.patch.object(executor, 'mesh_quality', return_value={'passed': True}), \
                 mock.patch.object(executor, 'execute', side_effect=lambda cmd, case, env, log:
                                   {'command': cmd, 'exit_code': 0, 'elapsed_seconds': 0.0, 'log': str(case / log)}):
                rc = executor.main(['--case', str(root), '--config', cfg_path,
                                    '--force-unsanctioned', '--steps', 'simpleFoam'])
            self.assertEqual(rc, 0)
            manifest = json.loads((root / 'run_manifest.json').read_text())
            self.assertTrue(manifest['contract']['forced'])
            self.assertFalse(manifest['contract']['execution_allowed'])
            # Force only lifts the gate; it must never mark engineering acceptance.
            self.assertFalse(manifest['engineering_acceptance'])

    def test_authorized_config_is_allowed_and_checked(self):
        """A synthetic execution-ready config passes the gate (contract.checked True)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_path = self._write_config(root, self._authorized_config())
            with contextlib.redirect_stderr(io.StringIO()), \
                 mock.patch.object(executor, 'check_case_complete'), \
                 mock.patch.object(executor, 'is_sst', return_value=False), \
                 mock.patch.object(executor, 'mesh_quality', return_value={'passed': True}), \
                 mock.patch.object(executor, 'execute', side_effect=lambda cmd, case, env, log:
                                   {'command': cmd, 'exit_code': 0, 'elapsed_seconds': 0.0, 'log': str(case / log)}):
                rc = executor.main(['--case', str(root), '--config', cfg_path, '--steps', 'simpleFoam'])
            self.assertEqual(rc, 0)
            manifest = json.loads((root / 'run_manifest.json').read_text())
            self.assertTrue(manifest['contract']['checked'])
            self.assertTrue(manifest['contract']['execution_allowed'])
            self.assertFalse(manifest['contract']['forced'])
            self.assertEqual(manifest['contract']['config_id'], 'synthetic_authorized_idealized')
            self.assertFalse(manifest['engineering_acceptance'])


if __name__=='__main__':
    unittest.main()
