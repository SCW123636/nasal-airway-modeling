"""Persistent local CFD jobs. Patient previews never authorize patient CFD.

The independent worker shares CT import's execution_lock and invokes the
existing plane-Poiseuille runner in one new native Linux case directory.
No solver is invoked during import, catalog construction or environment probes.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

from ct_case_pipeline import (execution_lock, now, process_alive, read_json,
                              sha256, write_json)
from patient_cfd_admission import ENGINEERING_CASE_RE

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_SCRIPT = ROOT / 'work/07_cfd_pipeline/solver_reference/run_reference.py'
PRESSURE_SCRIPT = ROOT / 'work/lib/openfoam_pressure_adapter.py'
PATIENT_SCRIPT = ROOT / 'work/lib/patient_cfd_runner.py'
JOB_RE = re.compile(r's_[0-9a-f]{24}')
EXISTING = ('p0', 'p1', 'p2', 'p3', 'p3t1')
LEVELS = ('coarse', 'medium', 'fine')
SCENARIOS = ('unequal', 'symmetric', 'swapped_labels')
RUN_ACTIONS = ('run_reference', 'run_pressure_feedback', 'run_patient_engineering')
DISTRO = 'Ubuntu-22.04'
TERMINAL = ('completed', 'failed', 'interrupted')
FIXED_PARAMETERS = {'bulk_U_m_s': 0.1, 'gap_H_m': 0.002,
                    'empty_width_W_m': 0.001, 'L_m': 0.04,
                    'Q_m3_s': 2e-7, 'Q_L_min': 0.012,
                    'outlet_gauge_p_Pa': 0, 'model': 'laminar'}


def windows_to_wsl(path):
    path = Path(path).resolve()
    if not path.drive or not re.fullmatch(r'[A-Za-z]:', path.drive):
        raise ValueError('WSL 转换仅支持本机盘符路径')
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def probe_environment():
    """Read-only WSL tool discovery; never runs mesh or solver commands."""
    if not shutil.which('wsl.exe'):
        return {'available': False, 'error': '本机未找到 wsl.exe', 'source': 'shutil.which(wsl.exe)'}
    script = (
        "import json,os,pathlib,shutil; "
        "tools=['python3','blockMesh','checkMesh','simpleFoam','foamToVTK']; "
        "print(json.dumps({'home':str(pathlib.Path.home()),'cpu_count':os.cpu_count(),"
        "'load_average':list(os.getloadavg()),'tools':{x:shutil.which(x) for x in tools},"
        "'tutorial_available':pathlib.Path('/usr/share/doc/openfoam-examples/examples/"
        "incompressible/simpleFoam/pitzDaily/system/fvSchemes').is_file()}))"
    )
    command = ['wsl.exe', '-d', DISTRO, '--', 'python3', '-c', script]
    try:
        process = subprocess.run(command, capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=12,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if process.returncode:
            return {'available': False, 'error': process.stderr.strip()[:1200],
                    'exit_code': process.returncode, 'source': 'read-only WSL Python tool discovery'}
        result = json.loads(process.stdout.strip())
        result.update(available=True, source='read-only WSL Python tool discovery', distro=DISTRO)
        return result
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {'available': False, 'error': str(exc), 'source': 'read-only WSL Python tool discovery'}


def environment_checks(environment):
    checks = [{'name': 'wsl_environment', 'passed': environment.get('available') is True,
               'source': environment.get('source'), 'detail': environment.get('error') or DISTRO}]
    if environment.get('available'):
        for name in ('python3', 'blockMesh', 'checkMesh', 'simpleFoam', 'foamToVTK'):
            path = environment.get('tools', {}).get(name)
            checks.append({'name': name, 'passed': bool(path),
                           'source': 'WSL shutil.which', 'detail': path or '未安装或不在 PATH'})
        home = environment.get('home', '')
        native = home.startswith('/') and not home.startswith('/mnt/') and '..' not in PurePosixPath(home).parts
        checks.append({'name': 'native_linux_workspace', 'passed': native,
                       'source': 'WSL pathlib.Path.home()', 'detail': home})
        checks.append({'name': 'tutorial_dictionary', 'passed': environment.get('tutorial_available') is True,
                       'source': 'WSL filesystem probe', 'detail': '既有 runner 使用官方 v1912 fvSchemes'})
    return checks


class SimulationJobs:
    def __init__(self, case_manager, review_root, job_root=None, environment_probe=None):
        self.case_manager = case_manager
        self.review_root = Path(review_root).resolve()
        self.root = Path(job_root or (case_manager.root / 'simulation_jobs')).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.environment_probe = environment_probe or probe_environment
        self.patient_input_root = Path(case_manager.root) / 'patient_cfd_inputs'
        self._environment = None
        self._environment_time = 0

    def environment(self, refresh=False):
        with self.lock:
            if refresh or self._environment is None or time.monotonic() - self._environment_time > 30:
                self._environment = self.environment_probe()
                self._environment_time = time.monotonic()
            return self._environment

    def patient(self, case, data=None):
        from patient_cfd_admission import admission, registered_cases
        reasons = []
        if case in EXISTING:
            source = self.review_root / case / 'landmarks.json'
            if not source.is_file():
                raise FileNotFoundError('未找到病例候选')
            proposal = read_json(source)
            reasons.append('现有候选状态：' + str(proposal.get('status', 'unknown')) + '；不等于最终几何批准')
            artifacts = [{'name': 'landmark_review', 'label': '候选点位与 CT 证据',
                          'url': '/landmark-review/index.html?case=' + case}]
            geometry_status = 'candidate_only'
        elif case not in registered_cases(self.patient_input_root):
            data = data or self.case_manager.get(case)
            artifacts = [{'name': key, 'label': key, 'url': value}
                         for key, value in (data.get('artifacts') or {}).items()
                         if isinstance(value, str) and value.startswith('/case-assets/' + case + '/')]
            geometry_status = 'boundary_draft' if data.get('boundary_preview', {}).get('status') == 'generated' else 'candidate_only'
            if data.get('status') != 'review_recorded':
                reasons.append('当前点位审核未完成，病例状态：' + str(data.get('status', 'unknown')))
            try:
                self.case_manager.load_boundary_review(case)
            except (ValueError, FileNotFoundError, KeyError) as exc:
                reasons.append('边界审核未准入：' + str(exc))
        else:
            geometry_status, artifacts = 'content_bound_engineering_input', []
        eligibility = admission(case, self.patient_input_root, self.patient_source_binding(case, data))
        checks = eligibility['checks']
        if case == 'p0':
            evidence = ROOT / 'outputs/T-020/fixed_clip_results.json'
            if evidence.is_file():
                diagnostic = read_json(evidence).get('cases',{}).get('p0',{})
                inputs = diagnostic.get('inputs',{})
                if inputs and all(Path(path).is_file() and sha256(Path(path)) == expected for path,expected in inputs.items()):
                    actual = diagnostic.get('actual',{})
                    details = actual.get('details') or {}
                    checks.append({'name':'fixed_plane_outlet_selection','passed':actual.get('passed') is True,
                                   'source':'outputs/T-020/fixed_clip_results.json; current surface/landmark SHA256 matched',
                                   'detail':'固定切面未移动；出口删除选区覆盖既有鼻孔端盖 ' + str(details.get('conflicting_triangles','未获得')) +
                                            ' 三角形，严格穿过切面 ' + str(details.get('strictly_crossing_plane_triangles','未获得')) +
                                            '；保护门拒绝。此为选区/拓扑证据，不是切面解剖错误结论。'})
        if eligibility['passed'] and not PATIENT_SCRIPT.is_file():
            checks.append({'name':'patient_runner','passed':False,'detail':'患者真实工程适配入口缺失','source':str(PATIENT_SCRIPT)})
        allowed = eligibility['passed'] and all(check['passed'] for check in checks) and PATIENT_SCRIPT.is_file()
        return {'id': case, 'label': case + (' · 独立患者工程示例' if ENGINEERING_CASE_RE.fullmatch(case) else ' · 鼻腔患者预览'), 'kind': 'patient',
                'run_action': 'run_patient_engineering', 'run_allowed': allowed,
                'blocking_reasons': [c['detail'] for c in checks if not c['passed']],
                'clinical_readiness_reasons': reasons + eligibility.get('clinical_readiness_reasons', []),
                'clinical_validation': 'not_validated', 'engineering_checks': checks,
                'geometry_status': geometry_status, 'mesh_status': 'bound_engineering_input' if allowed else 'not_admitted',
                'solver_status': 'engineering_trial_available' if allowed else 'not_admitted', 'artifacts': artifacts,
                'recommended_settings': {}}

    def patient_source_binding(self, case, data=None):
        if case in EXISTING:
            source = self.review_root / case / 'landmarks.json'
            if not source.is_file():
                return None
            binding = {'kind':'existing_landmark_source','landmarks_sha256':sha256(source)}
            surface = Path('C:/ts_work/batch27_surfaces') / case / 'source_surface.vtp'
            if surface.is_file():
                binding['source_surface_sha256'] = sha256(surface)
            return binding
        if ENGINEERING_CASE_RE.fullmatch(case):
            return None
        from ct_case_pipeline import case_dir
        folder = case_dir(self.case_manager.root, case)
        state = folder / 'case.json'
        data = data or self.case_manager.get(case)
        # Current public state content captures revision/input changes. Private
        # review records are independently hashed when present.
        binding = {'kind':'uploaded_case_revision','case_state_sha256':sha256(state)}
        for name in ('boundary_review.json','landmarks.json','review_config_confirmed.json'):
            path = folder / 'private' / name
            if path.is_file():
                binding[name + '_sha256'] = sha256(path)
        return binding

    def reference(self):
        checks = environment_checks(self.environment())
        checks.append({'name': 'reference_runner', 'passed': REFERENCE_SCRIPT.is_file(),
                       'source': 'work/07_cfd_pipeline/solver_reference/run_reference.py',
                       'detail': '复用已有真实 blockMesh/checkMesh/simpleFoam/foamToVTK 入口'})
        reasons = [c['name'] + '：' + str(c['detail']) for c in checks if not c['passed']]
        return {'id': 'reference_channel', 'label': '平行板气流参考 · 非患者', 'kind': 'reference',
                'run_action': 'run_reference',
                'run_allowed': not reasons, 'blocking_reasons': reasons,
                'geometry_status': 'runner_generated_reference', 'mesh_status': 'generated_on_new_run',
                'solver_status': 'available' if not reasons else 'environment_blocked',
                'artifacts': [], 'fixed_parameters': FIXED_PARAMETERS,
                'parameters': FIXED_PARAMETERS, 'recommended_settings': {'levels': ['coarse']}}

    def pressure_reference(self):
        checks = environment_checks(self.environment())
        checks.append({'name':'real_pressure_adapter','passed':PRESSURE_SCRIPT.is_file(),
                       'source':str(PRESSURE_SCRIPT.relative_to(ROOT)), 'detail':'真实共同静压、自然分流、双支路三对照'})
        return {'id':'reference_split_feedback','label':'共同压力与自然分流参考 · 非患者','kind':'reference',
                'run_action':'run_pressure_feedback','run_allowed':all(c['passed'] for c in checks),
                'blocking_reasons':[c['detail'] for c in checks if not c['passed']],
                'engineering_checks':checks,'clinical_validation':'not_validated',
                'geometry_status':'runner_generated_reference','mesh_status':'generated_on_new_run',
                'solver_status':'available','artifacts':[],
                'fixed_parameters':{'target_flow_L_min':1.,'outlet_gauge_p_Pa':0.,'model':'laminar','boundary_strategy':'common_inlet_pressure_feedback'},
                'recommended_settings':{'scenarios':list(SCENARIOS)}}

    def catalog(self):
        from patient_cfd_admission import registered_cases
        cases = [self.reference(), self.pressure_reference()]
        for case in EXISTING:
            if (self.review_root / case / 'landmarks.json').is_file():
                cases.append(self.patient(case))
        cases.extend(self.patient(data['id'], data) for data in self.case_manager.list())
        known = {item['id'] for item in cases}
        cases.extend(self.patient(case) for case in registered_cases(self.patient_input_root) if case not in known)
        return {'schema': 'nasal_simulation_catalog/v1', 'cases': cases}

    def preflight(self, case, refresh=False):
        if case not in ('reference_channel','reference_split_feedback'):
            item = self.patient(case)
            checks = item['engineering_checks'] + environment_checks(self.environment(refresh))
            return {'passed': all(c['passed'] for c in checks), 'case_id': case, 'patient_data': True,
                    'source': '当前病例、boundary_review 与患者准入契约',
                    'checks': checks, 'environment':self.environment(), 'clinical_validation':'not_validated',
                    'blocking_reasons': [c['detail'] for c in checks if not c['passed']]}
        checks = environment_checks(self.environment(refresh))
        source = REFERENCE_SCRIPT if case == 'reference_channel' else PRESSURE_SCRIPT
        checks.append({'name': 'reference_runner', 'passed': source.is_file(),
                       'source': str(source.relative_to(ROOT)),
                       'detail': sha256(source) if source.is_file() else '求解入口缺失'})
        return {'passed': all(c['passed'] for c in checks), 'case_id': case, 'patient_data': False,
                'checked_at': now(), 'checks': checks, 'environment': self.environment(),
                'fixed_parameters': FIXED_PARAMETERS,
                'blocking_reasons': [c['name'] + '：' + str(c['detail']) for c in checks if not c['passed']]}

    def directory(self, job_id):
        if not isinstance(job_id, str) or not JOB_RE.fullmatch(job_id):
            raise ValueError('计算任务编号无效')
        return self.root / job_id

    def raw(self, job_id):
        path = self.directory(job_id) / 'job.json'
        if not path.is_file():
            raise FileNotFoundError('未找到计算任务')
        return read_json(path)

    def get(self, job_id):
        with self.lock:
            data = self.raw(job_id)
            if data['status'] not in TERMINAL:
                age = time.time() - (self.directory(job_id) / 'job.json').stat().st_mtime
                if age > 60 and not process_alive(data.get('worker_pid')) and not process_alive(data.get('solver_pid')):
                    data.update(status='interrupted', stage='interrupted', updated_at=now(),
                                error='计算工作进程已中断；保留原任务证据，不自动重跑')
                    write_json(self.directory(job_id) / 'job.json', data)
            return self.public(data)

    def public(self, data):
        result = {key: value for key, value in data.items()
                  if key not in ('asset_paths', 'lock_root', 'review_root', 'worker_pid', 'solver_pid', 'command')}
        log = self.directory(data['id']) / 'execution.log'
        if log.is_file():
            with log.open('rb') as stream:
                stream.seek(max(0, log.stat().st_size - 8192))
                result['log_excerpt'] = stream.read().decode('utf-8', errors='replace')
        else:
            result['log_excerpt'] = ''
        return result

    def list(self):
        return sorted([self.get(path.parent.name) for path in self.root.glob('s_*/job.json')],
                      key=lambda item: item['created_at'], reverse=True)

    def start(self, payload):
        if not isinstance(payload, dict) or set(payload) - {'case_id', 'action', 'settings'}:
            raise ValueError('只接受 case_id、action、settings')
        case, action = payload.get('case_id'), payload.get('action')
        if action not in ('preflight', *RUN_ACTIONS):
            raise ValueError('action 只支持 preflight、run_reference、run_pressure_feedback、run_patient_engineering')
        settings = payload.get('settings', {})
        allowed_settings = {'levels'} if case == 'reference_channel' else {'scenarios'} if case == 'reference_split_feedback' else set()
        if not isinstance(settings, dict) or set(settings) - allowed_settings:
            raise ValueError('参考参数固定；settings 仅支持 levels，不接受流量或压力覆盖')
        levels = settings.get('levels', ['coarse'])
        if (not isinstance(levels, list) or not levels or len(levels) > 3
                or any(level not in LEVELS for level in levels) or len(set(levels)) != len(levels)):
            raise ValueError('levels 仅支持不重复的 coarse、medium、fine')
        scenarios = settings.get('scenarios', list(SCENARIOS))
        if not isinstance(scenarios,list) or not scenarios or len(scenarios)>3 or len(set(scenarios)) != len(scenarios) or any(s not in SCENARIOS for s in scenarios):
            raise ValueError('scenarios 仅支持不重复的 unequal、symmetric、swapped_labels')
        normalized = {'levels':levels} if case == 'reference_channel' else {'scenarios':scenarios} if case == 'reference_split_feedback' else {}
        if case not in ('reference_channel','reference_split_feedback'):
            item = self.patient(case)
            if action == 'run_reference':
                raise ValueError('患者运行拒绝：' + '；'.join(item['blocking_reasons']))
        else:
            item = self.reference() if case == 'reference_channel' else self.pressure_reference()
        if action != 'preflight' and (action != item['run_action'] or not item['run_allowed']):
            raise ValueError('计算入口拒绝：' + '；'.join(item['blocking_reasons'] or ['action 与病例类型不匹配']))
        with self.lock:
            if action in RUN_ACTIONS and any(job['action'] in RUN_ACTIONS
                                                and job['status'] not in TERMINAL for job in self.list()):
                raise ValueError('已有参考计算等待或运行中，请等待该任务结束')
            job_id = 's_' + uuid.uuid4().hex[:24]
            directory = self.directory(job_id)
            directory.mkdir(exist_ok=False)
            data = {'schema': 'nasal_simulation_job/v1', 'id': job_id, 'case_id': case,
                    'action': action, 'settings': normalized, 'status': 'queued',
                    'stage': 'queued', 'created_at': now(), 'updated_at': now(),
                    'preflight': None, 'result': None, 'artifacts': [], 'error': None,
                    'exit_code': None, 'worker_pid': None, 'solver_pid': None,
                    'lock_root': str(self.case_manager.root), 'review_root': str(self.review_root),
                    'asset_paths': {}}
            if action == 'run_patient_engineering':
                from patient_cfd_admission import admission
                current = self.patient_source_binding(case)
                eligible = admission(case,self.patient_input_root,current)
                data['patient_binding'] = {'current_source_binding':current,'admission_sha256':eligible['admission_sha256']}
            write_json(directory / 'job.json', data)
            try:
                self._spawn(directory)
            except OSError as exc:
                data.update(status='failed', stage='failed', error=str(exc), updated_at=now())
                write_json(directory / 'job.json', data)
            return self.get(job_id)

    def _spawn(self, directory):
        with (directory / 'worker.log').open('ab') as output:
            flags = (getattr(subprocess, 'DETACHED_PROCESS', 0)
                     | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)) if os.name == 'nt' else 0
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', str(directory)],
                             cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                             creationflags=flags, start_new_session=os.name != 'nt', close_fds=True)

    def asset(self, job_id, name):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
            raise FileNotFoundError('计算产物名称无效')
        data = self.raw(job_id)
        relative = data.get('asset_paths', {}).get(name)
        if not relative:
            raise FileNotFoundError('未找到显式计算产物')
        target = (self.directory(job_id) / relative).resolve()
        if not target.is_relative_to(self.directory(job_id).resolve()) or not target.is_file():
            raise FileNotFoundError('计算产物路径越界或缺失')
        return target


def worker(directory):
    directory = Path(directory).resolve()
    data = read_json(directory / 'job.json')
    if data['status'] in TERMINAL:
        return 1  # A closed or finished job is never restarted.

    def save(**fields):
        data.update(fields, updated_at=now())
        write_json(directory / 'job.json', data)

    def asset(name, path, label):
        data['asset_paths'][name] = path.relative_to(directory).as_posix()
        data['artifacts'].append({'name': name, 'label': label,
                                  'url': '/simulation-assets/' + data['id'] + '/' + name})

    class ReadOnlyCases:
        def __init__(self, root):
            self.root = Path(root)
        def get(self, case):
            from ct_case_pipeline import case_dir
            return read_json(case_dir(self.root, case) / 'case.json')
        def load_boundary_review(self, case):
            # Instantiate the real validator without a pipeline thread or recovery writes.
            from ct_case_pipeline import CaseManager
            manager = object.__new__(CaseManager)
            manager.root, manager.lock = self.root, threading.RLock()
            return manager.load_boundary_review(case)

    manager = SimulationJobs(ReadOnlyCases(data['lock_root']), data['review_root'], directory.parent)
    save(status='running', stage='preflight', worker_pid=os.getpid())
    try:
        if data['action'] == 'preflight':
            report = manager.preflight(data['case_id'], refresh=True)
            write_json(directory / 'preflight.json', report)
            asset('preflight.json', directory / 'preflight.json', '真实准入预检')
            save(preflight=report, status='completed', stage='completed', exit_code=0)
            return 0
        save(stage='waiting_cpu')
        with execution_lock(Path(data['lock_root'])):
            if data['action'] in ('run_pressure_feedback','run_patient_engineering'):
                return run_pressure_job(data, directory, manager, save, asset)
            save(stage='preflight')
            report = manager.preflight('reference_channel', refresh=True)
            write_json(directory / 'preflight.json', report)
            asset('preflight.json', directory / 'preflight.json', '真实环境与入口预检')
            save(preflight=report)
            if not report['passed']:
                raise RuntimeError('参考预检未通过：' + '；'.join(report['blocking_reasons']))
            environment = report['environment']
            load = environment.get('load_average', [])[0]
            if load / max(environment.get('cpu_count') or 1, 1) > .8:
                raise RuntimeError('WSL 平均负载超过 80%：' + str(load))
            source_hash = sha256(REFERENCE_SCRIPT)
            work_dir = environment['home'].rstrip('/') + '/nasal_cfd_workspace_jobs'
            export = directory / 'export'
            export.mkdir(exist_ok=False)
            command = ['wsl.exe', '-d', DISTRO, '--', 'env', 'OMP_NUM_THREADS=1',
                       'OPENBLAS_NUM_THREADS=1', 'MKL_NUM_THREADS=1', 'nice', '-n', '10',
                       'python3', windows_to_wsl(REFERENCE_SCRIPT), '--work-dir', work_dir,
                       '--tag', data['id'], '--levels', *data['settings']['levels'],
                       '--export-dir', windows_to_wsl(export)]
            write_json(directory / 'input_fingerprint.json',
                       {'runner_sha256': source_hash, 'settings': data['settings'],
                        'native_linux_run': work_dir + '/' + data['id'], 'created_at': now()})
            with (directory / 'execution.log').open('w', encoding='utf-8') as log:
                log.write(json.dumps({'command': command, 'runner_sha256': source_hash}) + '\n');log.flush()
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, encoding='utf-8', errors='replace',
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                save(stage='mesh', solver_pid=process.pid, command=command)
                for line in process.stdout:
                    log.write(line);log.flush()
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    commands = record.get('command', [])
                    if commands and commands[0] == 'checkMesh':
                        save(stage='solver')
                    elif commands and commands[0] == 'simpleFoam':
                        save(stage='export')
                    elif commands and commands[0] == 'foamToVTK':
                        save(stage='results')
                code = process.wait()
                save(exit_code=code, solver_pid=None)
            asset('execution.log', directory / 'execution.log', '本次真实执行日志')
            manifest_path = export / data['id'] / 'run_manifest.json'
            if manifest_path.is_file():
                manifest = read_json(manifest_path)
                asset('run_manifest.json', manifest_path, '本次原始参考运行记录')
                cases = []
                for record in manifest.get('cases', []):
                    cases.append({'level': record['level'], 'cells': record['cells'],
                                  'converged': record.get('SIMPLE_converged'),
                                  'mass_imbalance_fraction': record.get('mass_imbalance_fraction'),
                                  'delta_p_boundary_Pa': record.get('delta_p_boundary_Pa')})
                data['result'] = {'patient_data': False, 'reference_type': 'plane_poiseuille',
                                  'parameters': manifest.get('parameters'),
                                  'analytical': manifest.get('analytical'), 'cases': cases,
                                  'execution_status': manifest.get('execution_status'),
                                  'validation_status': 'awaiting_independent_review'}
            for level in data['settings']['levels']:
                for name in ('log.blockMesh', 'log.checkMesh', 'log.simpleFoam', 'log.foamToVTK'):
                    path = export / data['id'] / level / name
                    if path.is_file():
                        asset(level + '-' + name, path, level + ' · ' + name)
            if code:
                raise RuntimeError('真实参考进程退出码：' + str(code))
            if not manifest_path.is_file() or data['result']['execution_status'] != 'completed':
                raise RuntimeError('进程结束但本次原始运行记录缺失或未完成')
            if sha256(REFERENCE_SCRIPT) != source_hash:
                raise RuntimeError('运行期间求解入口变化，本次结果保留但不能按原输入验收')
            save(stage='viewer_export')
            viewing = export_reference_viewer(directory, manifest)
            asset('viewer_mesh.json', directory / 'viewer_mesh.json', '本次真实速度与压力字段')
            asset('viewer.json', directory / 'viewer.json', '本次三维索引')
            data['artifacts'].append({'name': 'viewer', 'label': '三维速度 / 压力',
                                      'url': '/viewer/index.html?manifest=/simulation-assets/' + data['id'] + '/viewer.json'})
            data['result']['viewer_export'] = viewing
            save(status='completed', stage='completed')
            return 0
    except Exception as exc:
        if (directory / 'execution.log').is_file() and not any(a['name'] == 'execution.log' for a in data['artifacts']):
            asset('execution.log', directory / 'execution.log', '失败执行日志')
        save(status='failed', stage='failed', error=str(exc))
        return 1


def run_pressure_job(data, directory, manager, save, asset):
    """Same persistent worker/CPU lock, with new real adapters and no HTTP paths."""
    report = manager.preflight(data['case_id'], refresh=True)
    write_json(directory / 'preflight.json', report)
    asset('preflight.json', directory / 'preflight.json', '真实工程输入与环境预检')
    save(preflight=report, stage='preflight')
    if not report['passed']:
        raise RuntimeError('工程预检未通过：' + '；'.join(report['blocking_reasons']))
    environment = report['environment']
    if environment.get('load_average',[0])[0] / max(environment.get('cpu_count') or 1,1) > .8:
        raise RuntimeError('WSL 平均负载超过80%')
    native = environment['home'].rstrip('/') + '/nasal_cfd_workspace_jobs/' + data['id']
    export = directory / 'export' / data['id']
    export.parent.mkdir(exist_ok=True)
    patient = data['action'] == 'run_patient_engineering'
    source = PATIENT_SCRIPT if patient else PRESSURE_SCRIPT
    source_hash = sha256(source)
    command = ['wsl.exe','-d',DISTRO,'--','env','OMP_NUM_THREADS=1','OPENBLAS_NUM_THREADS=1',
               'MKL_NUM_THREADS=1','taskset','-c','0','nice','-n','10','python3', windows_to_wsl(source),
               '--work-dir',native,'--export-dir',windows_to_wsl(export)]
    if patient:
        from patient_cfd_admission import admission
        eligibility = admission(data['case_id'], manager.patient_input_root, manager.patient_source_binding(data['case_id']))
        if not eligibility['passed']:
            raise RuntimeError('患者输入在启动前变化：' + '；'.join(eligibility['blocking_reasons']))
        snapshot = {'current_source_binding':manager.patient_source_binding(data['case_id']),
                    'admission_sha256':eligibility['admission_sha256']}
        if snapshot != data.get('patient_binding'):
            raise RuntimeError('排队期间患者输入或准入记录变化；必须按新输入提交新任务')
        command += ['--patient-input',windows_to_wsl(Path(eligibility['folder']))]
        command += ['--expected-admission-sha',eligibility['admission_sha256']]
        if snapshot['current_source_binding']:
            command += ['--source-binding',json.dumps(snapshot['current_source_binding'])]
    else:
        command += ['--scenarios',*data['settings']['scenarios']]
    write_json(directory / 'input_fingerprint.json', {'runner_sha256':source_hash,'native_linux_run':native,
                                                     'case_id':data['case_id'],'settings':data['settings']})
    asset('input_fingerprint.json', directory / 'input_fingerprint.json', '本次输入与代码指纹')
    write_json(directory / 'live_status.json', {'stage':'starting','native_case':native,'updated_at':now()})
    asset('live_status.json',directory / 'live_status.json','实际求解进度与日志尾')
    with (directory / 'execution.log').open('w',encoding='utf-8') as log:
        log.write(json.dumps({'command':command,'runner_sha256':source_hash}) + '\n');log.flush()
        process = subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
                                   encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        save(stage='solver',solver_pid=process.pid,command=command)
        def drain():
            for line in process.stdout:
                log.write(line);log.flush()
        reader = threading.Thread(target=drain,daemon=True);reader.start()
        while process.poll() is None:
            telemetry = probe_live_pressure_run(native)
            if telemetry:
                telemetry['updated_at'] = now()
                write_json(directory / 'live_status.json',telemetry)
                save(stage=telemetry.get('stage','solver'),live_progress=telemetry)
            time.sleep(3)
        code = process.wait()
        reader.join(timeout=5)
    asset('execution.log',directory / 'execution.log','本次真实压力求解日志')
    save(exit_code=code,solver_pid=None,stage='results')
    summary = export / ('patient_engineering_report.json' if patient else 'feedback_suite_report.json')
    if summary.is_file():
        result = read_json(summary)
        result.update(reference_type=None if patient else 'split_pressure_feedback',patient_data=patient)
        data['result'] = result
        asset(summary.name,summary,'本次工程求解与质量记录')
    for path in sorted(export.rglob('evaluation_*.json')):
        name = path.relative_to(export).as_posix().replace('/','-')
        asset(name,path,'原始评估：' + path.parent.parent.name)
    for path in sorted(export.rglob('log.*')):
        name = path.relative_to(export).as_posix().replace('/','-')
        asset(name,path,'原始执行证据：' + path.name)
    if sha256(source) != source_hash:
        raise RuntimeError('运行期间入口变动；证据保留但不能按冻结版本验收')
    if patient:
        from patient_cfd_admission import admission
        current = manager.patient_source_binding(data['case_id'])
        final_admission = admission(data['case_id'],manager.patient_input_root,current)
        if not final_admission['passed'] or {'current_source_binding':current,'admission_sha256':final_admission.get('admission_sha256')} != data['patient_binding']:
            raise RuntimeError('运行期间患者源输入或准入记录变化；原始结果仅保留证据')
    if not patient and code == 0 and summary.is_file():
        export_pressure_reference_viewer(directory, data['result'], asset, data)
    if patient and summary.is_file():
        # Raw trial fields remain available without mislabeling an unreviewed
        # patient trial as a clinically admitted nasal_cfd_result/v1.
        for path in sorted(export.rglob('internal.vtu')):
            name = path.relative_to(export).as_posix().replace('/','-')
            asset(name,path,'患者工程试算原始VTU（非临床结果）')
        try:
            from patient_cfd_viewer import export_patient_trial_viewer
        except ImportError:
            data['result']['viewer_export_status'] = 'raw_vtu_available_viewer_adapter_pending'
        else:
            try:
                data['result']['viewer_export'] = export_patient_trial_viewer(directory,data['result'],asset,data)
            except Exception as exc:
                data['result']['viewer_export_error'] = str(exc)
    if code or not summary.is_file():
        raise RuntimeError('真实压力求解退出码：' + str(code) + '；失败点不会进入反馈，原始证据保留')
    save(status='completed',stage='completed')
    return 0


def probe_live_pressure_run(native):
    """Read real run_status/solver tails without launching a solver or copying fields."""
    code = '''import json,pathlib,re,sys
root=pathlib.Path(sys.argv[1])
files=list(root.rglob("run_status.json")) if root.exists() else []
if files:
 path=max(files,key=lambda p:p.stat().st_mtime)
 data=json.loads(path.read_text())
 log=path.parent/"log.simpleFoam"
 tail=""
 if log.is_file():
  with log.open("rb") as stream:
   stream.seek(max(0,log.stat().st_size-12000));tail=stream.read().decode("utf-8","replace")
 iterations=re.findall(r"(?m)^Time = ([0-9.eE+-]+)",tail)
 command=data.get("current_command") or []
 step=command[0] if command else data.get("status")
 stage="mesh" if step in ("blockMesh","checkMesh","snappyHexMesh") else "export" if step=="foamToVTK" else "solver"
 print(json.dumps({"stage":stage,"evaluation":path.parent.name,"native_case":str(path.parent),"actual_step":step,"iteration":iterations[-1] if iterations else None,"runner_status":data.get("status"),"log_tail":tail[-2500:]}))
'''
    try:
        result = subprocess.run(['wsl.exe','-d',DISTRO,'--','python3','-c',code,native],
                                capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=10,
                                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else None
    except (OSError,subprocess.TimeoutExpired,ValueError):
        return None


def export_pressure_reference_viewer(directory, report, asset, data):
    """Reuse verified VTU field conversion, then restore truthful split identity."""
    import vtk
    name = 'unequal' if 'unequal' in report['scenarios'] else next(iter(report['scenarios']))
    trial = report['scenarios'][name]['evaluations'][-1]
    base = directory / 'export' / data['id']
    source_case = base / name / 'evaluations' / Path(trial['case']).name
    target = base / 'pressure_result'
    shutil.copytree(source_case,target)
    for source,destination in [('pressure_inlet_L','pressureIn'),('pressure_outlet','pressureOut')]:
        shutil.copytree(target / 'postProcessing' / source,target / 'postProcessing' / destination)
    files = list((target / 'VTK').rglob('internal.vtu'))
    if len(files) != 1:
        raise ValueError('最终双支路VTU缺失或不唯一')
    reader = vtk.vtkXMLUnstructuredGridReader();reader.SetFileName(str(files[0]));reader.Update()
    manifest = {'patient_data':False,'execution_status':'completed','package_version':'OpenFOAM-v1912',
                'parameters':{'empty_width_W_m':.01,'rho_kg_m3':1.2,'mu_Pa_s':1.81e-5},
                'cases':[{'level':'pressure_result','cells':reader.GetOutput().GetNumberOfCells(),
                          'commands':read_json(target / 'run_manifest.json')['steps'],
                          'mass_imbalance_fraction':trial['diagnostics']['flux']['mass_imbalance_frac']}]}
    viewing = export_reference_viewer(directory,manifest)
    mesh,viewer = read_json(directory / 'viewer_mesh.json'),read_json(directory / 'viewer.json')
    mesh['result']['provenance']['config_id'] = 'split_common_pressure_reference_' + name
    mesh['result']['diagnostics'] = {**trial['diagnostics'],'mass_imbalance_fraction':trial['diagnostics']['flux']['mass_imbalance_frac']}
    viewer['cases'][0].update(label='本次共同压力双支路参考 · ' + name,
                              note='本次实际 OpenFOAM 字段；共同入口静压与自然分流；非患者。')
    write_json(directory / 'viewer_mesh.json',mesh);write_json(directory / 'viewer.json',viewer)
    asset('pressure_result-log.simpleFoam',target / 'log.simpleFoam','展示字段的原始simpleFoam日志')
    asset('viewer_mesh.json',directory / 'viewer_mesh.json','本次真实共同压力字段')
    asset('viewer.json',directory / 'viewer.json','本次三维索引')
    data['artifacts'].append({'name':'viewer','label':'三维速度 / 压力',
                              'url':'/viewer/index.html?manifest=/simulation-assets/' + data['id'] + '/viewer.json'})
    report['viewer_export'] = viewing


def export_reference_viewer(directory, manifest):
    """Cut the new run's VTU fields; never use old or analytical flow arrays."""
    import numpy as np
    import vtk
    from vtk.util.numpy_support import vtk_to_numpy
    from cfd_contract import pressure_to_pa, validate_result
    directory = Path(directory)
    data = read_json(directory / 'job.json')
    if manifest.get('patient_data') is not False or manifest.get('execution_status') != 'completed':
        raise ValueError('三维导出仅接受本次实际完成的非患者运行')
    record = manifest['cases'][-1]
    if any(item['exit_code'] != 0 for item in record['commands']):
        raise ValueError('本次参考有失败命令，拒绝发布流场')
    case = directory / 'export' / data['id'] / record['level']
    sources = list((case / 'VTK').rglob('internal.vtu'))
    if len(sources) != 1:
        raise ValueError('本次最终 internal.vtu 缺失或不唯一')
    source = sources[0]
    pressure_files = [p for p in case.glob('*/p') if re.fullmatch(r'\d+(?:\.\d+)?', p.parent.name)]
    if not pressure_files:
        raise ValueError('本次压力维度文件缺失')
    pressure_file = max(pressure_files, key=lambda p: float(p.parent.name))
    if not re.search(r'dimensions\s*\[\s*0\s+2\s+-2\s+0\s+0\s+0\s+0\s*\]', pressure_file.read_text()):
        raise ValueError('OpenFOAM 压力维度不是运动学压力')
    reader = vtk.vtkXMLUnstructuredGridReader();reader.SetFileName(str(source));reader.Update()
    grid = reader.GetOutput()
    if grid.GetNumberOfCells() != record['cells']:
        raise ValueError('VTU 单元数与本次运行记录不符')
    parameters = manifest['parameters']
    plane = vtk.vtkPlane();plane.SetOrigin(0, 0, parameters['empty_width_W_m'] / 2);plane.SetNormal(0, 0, 1)
    cutter = vtk.vtkCutter();cutter.SetInputData(grid);cutter.SetCutFunction(plane);cutter.Update()
    triangles = vtk.vtkTriangleFilter();triangles.SetInputConnection(cutter.GetOutputPort());triangles.Update()
    poly = triangles.GetOutput()
    if not poly.GetNumberOfPoints() or not poly.GetNumberOfPolys():
        raise ValueError('实际 VTU 中面切片为空')
    cells = poly.GetPolys()
    if np.any(np.diff(vtk_to_numpy(cells.GetOffsetsArray())) != 3):
        raise ValueError('中面切片并非三角面')
    points = vtk_to_numpy(poly.GetPoints().GetData()).astype(float)
    indices = vtk_to_numpy(cells.GetConnectivityArray()).reshape(-1, 3)
    u, p = poly.GetPointData().GetArray('U'), poly.GetPointData().GetArray('p')
    if u is None or p is None:
        raise ValueError('实际 VTU 没有 U 或 p 点字段')
    velocity, pressure = vtk_to_numpy(u).astype(float), vtk_to_numpy(p).astype(float)
    if not all(np.isfinite(a).all() for a in (points, velocity, pressure)):
        raise ValueError('实际字段含非有限值')
    residuals = {}
    log = (case / 'log.simpleFoam').read_text()
    for name, value in re.findall(r'Solving for (\w+), Initial residual = ([\deE+.-]+)', log):
        residuals[name] = float(value)
    if not residuals:
        raise ValueError('原始求解日志没有残差证据')
    def series(name):
        files = sorted((case / 'postProcessing' / name).glob('*/surfaceFieldValue.dat'))
        if not files:
            raise ValueError('本次压力监测文件缺失：' + name)
        return np.loadtxt(files[-1], comments='#', ndmin=2)
    inlet, outlet = series('pressureIn'), series('pressureOut')
    if inlet.shape != outlet.shape or not np.array_equal(inlet[:, 0], outlet[:, 0]):
        raise ValueError('本次入口与出口压力监测时序不一致')
    tail = (parameters['rho_kg_m3'] * (inlet[:, 1] - outlet[:, 1]))[-20:]
    if len(tail) < 20 or abs(float(np.mean(tail))) == 0:
        raise ValueError('本次压力稳定性证据不足')
    diagnostics = {'mass_imbalance_fraction': record['mass_imbalance_fraction'],
                   'monitor_relative_change': float(np.ptp(tail) / abs(np.mean(tail))),
                   'residual_max': max(residuals.values()),
                   'monitor_definition': '(max-min)/abs(mean) over last 20 SIMPLE iterations',
                   'precision_note': 'Zero may mean below recorded precision, not exact arithmetic'}
    rho = parameters['rho_kg_m3']
    result = {'schema': 'nasal_cfd_result/v1', 'type': 'cfd_result',
              'geometry': {'kind': 'idealized', 'case_id': None},
              'clinical_validation': 'not_validated', 'numerical_validation': 'unchecked',
              'physics': {'turbulence_model': 'laminar', 'rho_kg_m3': rho, 'mu_Pa_s': parameters['mu_Pa_s']},
              'provenance': {'method': 'cfd_solver', 'solver_name': 'simpleFoam',
                             'solver_version': manifest['package_version'],
                             'run_id': data['id'] + '/' + record['level'],
                             'run_log': '/simulation-assets/' + data['id'] + '/' + record['level'] + '-log.simpleFoam',
                             'config_id': 'plane_poiseuille_v1912_reference',
                             'source_vtu_sha256': sha256(source),
                             'display_mapping': 'xyz = solver yzx; rigid rotation; m to mm',
                             'sampling': 'mid-plane of actual exported point-interpolated fields'},
              'diagnostics': diagnostics, 'parameters': parameters,
              'fields': {'velocity': {'unit': 'm/s', 'association': 'point', 'values': velocity[:, [1, 2, 0]].tolist()},
                         'pressure': {'unit': 'Pa', 'association': 'point', 'values': pressure_to_pa(pressure, 'm2/s2', rho),
                                      'quantity': 'static', 'reference': 'gauge', 'source_unit': 'm2/s2',
                                      'source_field': 'p', 'rho_kg_m3': rho, 'conversion': 'p_Pa = rho_kg_m3 * p_kinematic'},
                         'turbulence_intensity': None}, 'turbulence_intensity_status': 'not_applicable'}
    check = validate_result(result)
    if not check['valid']:
        raise ValueError('三维结果契约不通过：' + '; '.join(check['errors']))
    mesh = {'schema': 'candidate_surface_preview/v1', 'case': None, 'status': 'numerical_reference',
            'coordinate_system': 'synthetic_Cartesian', 'unit': 'mm', 'display_geometry_only': True,
            'cfd_ready': False, 'geometry': {'vertices': (points[:, [1, 2, 0]] * 1000).ravel().tolist(),
                                           'indices': indices.ravel().tolist()},
            'result': result, 'qc': {'result_contract': check, 'grid_validation': 'not_performed_for_this_job'}}
    viewer = {'schema': 'nasal_workspace/v1', 'patient_scan_count': 0, 'patient_cfd_results': 0,
              'cases': [{'id': data['id'], 'label': '本次真实平行板参考 · ' + record['level'],
                         'type': 'numerical_reference', 'mesh_url': '/simulation-assets/' + data['id'] + '/viewer_mesh.json',
                         'note': '本次 OpenFOAM 实际计算；非患者；三档网格验证未执行。', 'landmarks': []}]}
    write_json(directory / 'viewer_mesh.json', mesh)
    write_json(directory / 'viewer.json', viewer)
    return {'points': len(points), 'triangles': len(indices), 'source_vtu_sha256': sha256(source),
            'result_contract_valid': check['valid'], 'diagnostics': diagnostics}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    raise SystemExit(worker(parser.parse_args().worker))
