"""Focused lifecycle, boundary and runner tests without invoking CFD."""
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from ct_case_pipeline import CaseManager, read_json, write_json
import cfd_workspace_jobs as jobs


GOOD_ENV = {'available': True, 'source': 'isolated_test_fixture', 'home': '/home/test',
            'cpu_count': 4, 'load_average': [0., 0., 0.], 'tutorial_available': True,
            'tools': {name: '/usr/bin/' + name for name in ('python3', 'blockMesh', 'checkMesh', 'simpleFoam', 'foamToVTK')}}


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='simulation_jobs_')
        self.root = Path(self.tmp.name)
        self.cases = CaseManager(self.root / 'cases')
        self.reviews = self.root / 'reviews'
        self.reviews.mkdir()
        (self.reviews / 'p0').mkdir()
        write_json(self.reviews / 'p0/landmarks.json', {'status': 'proposals_not_clinically_validated'})
        self.jobs = jobs.SimulationJobs(self.cases, self.reviews, self.root / 'jobs', lambda: GOOD_ENV)

    def tearDown(self):
        self.cases.pool.shutdown(wait=True)
        self.tmp.cleanup()

    def create(self, action='preflight', case='reference_channel'):
        with patch.object(self.jobs, '_spawn'):
            return self.jobs.start({'case_id': case, 'action': action, 'settings': {'levels': ['coarse']} if case == 'reference_channel' else {}})

    def test_catalog_separates_reference_and_patient_current_case(self):
        catalog = self.jobs.catalog()
        self.assertEqual(catalog['schema'], 'nasal_simulation_catalog/v1')
        reference = next(c for c in catalog['cases'] if c['id']=='reference_channel')
        patient = next(c for c in catalog['cases'] if c['id']=='p0')
        split = next(c for c in catalog['cases'] if c['id']=='reference_split_feedback')
        self.assertEqual(split['run_action'],'run_pressure_feedback')
        self.assertTrue(reference['run_allowed'])
        self.assertEqual(reference['fixed_parameters']['Q_L_min'], .012)
        self.assertFalse(patient['run_allowed'])
        self.assertEqual(patient['id'], 'p0')
        self.assertEqual(patient['mesh_status'], 'not_admitted')
        self.assertIn('最终 CFD 表面', ' '.join(patient['blocking_reasons']))

    def test_patient_run_and_unknown_settings_are_rejected(self):
        with self.assertRaisesRegex(ValueError, '患者运行拒绝'):
            self.create('run_reference', 'p0')
        for settings in ({'flow_L_min': 15}, {'levels': ['unknown']}, {'levels': ['coarse', 'coarse']}):
            with self.assertRaises(ValueError):
                self.jobs.start({'case_id': 'reference_channel', 'action': 'run_reference', 'settings': settings})
        with self.assertRaises(ValueError):
            self.jobs.start({'case_id': 'reference_channel', 'action': 'run_reference', 'command': 'anything'})

    def test_bound_fixed_plane_rejection_is_reflected_in_catalog_run_permission(self):
        source = self.reviews / 'p0/landmarks.json'
        diagnostic = self.root / 'outputs/T-020/fixed_clip_results.json'
        write_json(diagnostic, {'cases': {'p0': {
            'inputs': {str(source): jobs.sha256(source)},
            'actual': {'passed': False, 'details': {'conflicting_triangles': 774,
                                                  'strictly_crossing_plane_triangles': 0}}}}})
        eligibility = {'passed': True, 'checks': [{'name': 'fixture_admission', 'passed': True,
                                                  'detail': 'fixture only'}]}
        with patch.object(jobs, 'ROOT', self.root), patch('patient_cfd_admission.admission', return_value=eligibility):
            patient = self.jobs.patient('p0')
        self.assertFalse(patient['run_allowed'])
        self.assertEqual(patient['solver_status'], 'not_admitted')
        self.assertIn('774', ' '.join(patient['blocking_reasons']))

    def test_preflight_worker_completes_without_solver_and_restart_reads_disk(self):
        created = self.create()
        directory = self.jobs.directory(created['id'])
        with patch.object(jobs, 'probe_environment', return_value=GOOD_ENV), patch.object(jobs.subprocess, 'Popen') as spawn:
            self.assertEqual(jobs.worker(directory), 0)
        spawn.assert_not_called()
        restored = jobs.SimulationJobs(self.cases, self.reviews, self.root / 'jobs', lambda: GOOD_ENV)
        loaded = restored.get(created['id'])
        self.assertEqual(loaded['status'], 'completed')
        self.assertTrue(loaded['preflight']['passed'])
        self.assertEqual(loaded['exit_code'], 0)
        self.assertNotIn('lock_root', loaded)
        self.assertEqual(jobs.worker(directory), 1)  # Never restart a finished job.
        self.assertEqual(restored.asset(created['id'], 'preflight.json'), directory / 'preflight.json')

    def test_patient_preflight_is_completed_report_of_failed_admission(self):
        created = self.create(case='p0')
        self.assertEqual(jobs.worker(self.jobs.directory(created['id'])), 0)
        data = self.jobs.get(created['id'])
        self.assertEqual(data['status'], 'completed')
        self.assertFalse(data['preflight']['passed'])
        self.assertTrue(data['preflight']['blocking_reasons'])
        self.assertIsNone(data['result'])

    def test_environment_missing_cannot_be_reported_passed(self):
        created = self.create('run_reference')
        with patch.object(jobs, 'probe_environment', return_value={'available': False, 'error': 'test missing', 'source': 'fixture'}), patch.object(jobs.subprocess, 'Popen') as spawn:
            self.assertEqual(jobs.worker(self.jobs.directory(created['id'])), 1)
        spawn.assert_not_called()
        data = self.jobs.get(created['id'])
        self.assertEqual(data['status'], 'failed')
        self.assertFalse(data['preflight']['passed'])
        self.assertIsNone(data['exit_code'])  # No invented solver exit code.
        self.assertIsNone(data['result'])

    def test_detached_launch_failure_and_dead_worker_are_persistent(self):
        with patch.object(self.jobs, '_spawn', side_effect=OSError('test launch failure')):
            created = self.jobs.start({'case_id': 'reference_channel', 'action': 'preflight'})
        self.assertEqual(created['status'], 'failed')
        self.assertIn('test launch failure', created['error'])
        created = self.create()
        path = self.jobs.directory(created['id']) / 'job.json'
        os.utime(path, (time.time() - 120, time.time() - 120))
        self.assertEqual(self.jobs.get(created['id'])['status'], 'interrupted')

    def test_live_worker_not_misclassified_and_only_one_reference_queued(self):
        created = self.create('run_reference')
        path = self.jobs.directory(created['id']) / 'job.json'
        data = read_json(path);data.update(status='running', worker_pid=os.getpid());write_json(path, data)
        os.utime(path, (time.time() - 120, time.time() - 120))
        self.assertEqual(self.jobs.get(created['id'])['status'], 'running')
        with self.assertRaisesRegex(ValueError, '已有参考计算'):
            self.create('run_reference')

    def test_asset_allowlist_and_directory_escape(self):
        created = self.create()
        directory = self.jobs.directory(created['id'])
        secret = directory / 'private.txt';secret.write_text('private')
        for name in ('private.txt', '../private.txt', '..\\private.txt', 'raw.dcm', 'job.json'):
            with self.assertRaises(FileNotFoundError):
                self.jobs.asset(created['id'], name)
        with self.assertRaises(ValueError):
            self.jobs.get('../not_a_job')
        data = self.jobs.raw(created['id']);data['asset_paths'] = {'outside.json': '../outside.json'}
        write_json(directory / 'job.json', data)
        (directory.parent / 'outside.json').write_text('{}')
        with self.assertRaises(FileNotFoundError):
            self.jobs.asset(created['id'], 'outside.json')

    def test_windows_wsl_paths_native_linux_requirement(self):
        self.assertTrue(jobs.windows_to_wsl(jobs.REFERENCE_SCRIPT).startswith('/mnt/d/'))
        wrong = GOOD_ENV | {'home': '/mnt/c/case'}
        check = next(c for c in jobs.environment_checks(wrong) if c['name'] == 'native_linux_workspace')
        self.assertFalse(check['passed'])

    def test_real_runner_command_failure_preserves_exit_and_releases_ct_lock(self):
        created = self.create('run_reference')
        directory = self.jobs.directory(created['id'])
        locked = []
        observed = []
        @contextmanager
        def locked_fixture(root):
            self.assertEqual(root, self.cases.root)
            locked.append(True)
            try:
                yield
            finally:
                locked.pop()
        class FailedProcess:
            pid = os.getpid()
            stdout = io.StringIO('original failed runner output\n')
            def wait(self):
                return 41
        def spawn(command, **kwargs):
            self.assertTrue(locked)
            observed.append(command)
            return FailedProcess()
        with patch.object(jobs, 'probe_environment', return_value=GOOD_ENV), patch.object(jobs, 'execution_lock', locked_fixture), patch.object(jobs.subprocess, 'Popen', side_effect=spawn):
            self.assertEqual(jobs.worker(directory), 1)
        self.assertFalse(locked)
        data = self.jobs.get(created['id'])
        self.assertEqual(data['exit_code'], 41)
        self.assertEqual(data['status'], 'failed')
        self.assertIn('original failed runner output', data['log_excerpt'])
        command = observed[0]
        self.assertIn(jobs.windows_to_wsl(jobs.REFERENCE_SCRIPT), command)
        self.assertEqual(command[command.index('--tag') + 1], created['id'])
        self.assertEqual(command[command.index('--work-dir') + 1], '/home/test/nasal_cfd_workspace_jobs')
        self.assertIsNone(data['result'])

    def test_new_run_viewer_fixture_units_identity_and_known_pressure(self):
        # Isolated one-cell known-answer VTU fixture, never represented as a real solver run.
        import vtk
        created = self.create('run_reference')
        directory = self.jobs.directory(created['id'])
        case = directory / 'export' / created['id'] / 'coarse'
        vtu_dir = case / 'VTK' / 'fixture_20';vtu_dir.mkdir(parents=True)
        pressure = case / '20/p';pressure.parent.mkdir()
        pressure.write_text('dimensions [0 2 -2 0 0 0 0];')
        (case / 'log.simpleFoam').write_text('Solving for p, Initial residual = 1e-7, Final residual = 1e-9\n')
        for name, value in [('pressureIn', 2), ('pressureOut', 1)]:
            path = case / 'postProcessing' / name / '0/surfaceFieldValue.dat';path.parent.mkdir(parents=True)
            path.write_text('\n'.join(f'{i} {value}' for i in range(20)))
        grid = vtk.vtkUnstructuredGrid();points = vtk.vtkPoints()
        for x, y, z in [(0,0,0),(.04,0,0),(.04,.002,0),(0,.002,0),(0,0,.001),(.04,0,.001),(.04,.002,.001),(0,.002,.001)]:
            points.InsertNextPoint(x, y, z)
        grid.SetPoints(points)
        hexahedron = vtk.vtkHexahedron()
        for i in range(8):
            hexahedron.GetPointIds().SetId(i, i)
        grid.InsertNextCell(hexahedron.GetCellType(), hexahedron.GetPointIds())
        vectors = vtk.vtkDoubleArray();vectors.SetName('U');vectors.SetNumberOfComponents(3)
        scalar = vtk.vtkDoubleArray();scalar.SetName('p')
        for i in range(8):
            vectors.InsertNextTuple3(.1, 0, 0);scalar.InsertNextValue(2)
        grid.GetPointData().AddArray(vectors);grid.GetPointData().AddArray(scalar)
        writer = vtk.vtkXMLUnstructuredGridWriter();writer.SetFileName(str(vtu_dir / 'internal.vtu'));writer.SetInputData(grid)
        self.assertEqual(writer.Write(), 1)
        manifest = {'patient_data': False, 'execution_status': 'completed', 'package_version': 'fixture-not-real-solver',
                    'parameters': {'empty_width_W_m': .001, 'rho_kg_m3': 1.2, 'mu_Pa_s': 1.81e-5},
                    'cases': [{'level': 'coarse', 'cells': 1, 'commands': [{'exit_code': 0}], 'mass_imbalance_fraction': 0.0}]}
        exported = jobs.export_reference_viewer(directory, manifest)
        self.assertTrue(exported['result_contract_valid'])
        mesh = read_json(directory / 'viewer_mesh.json')
        self.assertIsNone(mesh['case'])
        self.assertEqual(mesh['result']['numerical_validation'], 'unchecked')
        self.assertEqual(set(mesh['result']['fields']['pressure']['values']), {2.4})
        self.assertEqual(mesh['result']['fields']['velocity']['values'][0], [0, 0, .1])
        self.assertAlmostEqual(max(mesh['geometry']['vertices']), 40, places=4)
        self.assertIsNone(mesh['result']['fields']['turbulence_intensity'])
        pressure.write_text('dimensions [1 -1 -2 0 0 0 0];')
        with self.assertRaisesRegex(ValueError, '运动学压力'):
            jobs.export_reference_viewer(directory, manifest)

    def test_pressure_feedback_schema_and_cross_action_refusal(self):
        with patch.object(self.jobs,'_spawn'):
            created = self.jobs.start({'case_id':'reference_split_feedback','action':'run_pressure_feedback',
                                      'settings':{'scenarios':['unequal','symmetric','swapped_labels']}})
        self.assertEqual(created['settings']['scenarios'],list(jobs.SCENARIOS))
        with self.assertRaisesRegex(ValueError,'入口拒绝'):
            self.jobs.start({'case_id':'reference_channel','action':'run_patient_engineering'})
        with self.assertRaises(ValueError):
            self.jobs.start({'case_id':'reference_split_feedback','action':'run_pressure_feedback','settings':{'scenarios':['bad']}})


if __name__ == '__main__':
    unittest.main()
