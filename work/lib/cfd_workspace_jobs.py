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

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_SCRIPT = ROOT / 'work/07_cfd_pipeline/solver_reference/run_reference.py'
JOB_RE = re.compile(r's_[0-9a-f]{24}')
EXISTING = ('p0', 'p1', 'p2', 'p3', 'p3t1')
LEVELS = ('coarse', 'medium', 'fine')
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
        self._environment = None
        self._environment_time = 0

    def environment(self, refresh=False):
        with self.lock:
            if refresh or self._environment is None or time.monotonic() - self._environment_time > 30:
                self._environment = self.environment_probe()
                self._environment_time = time.monotonic()
            return self._environment

    def patient(self, case, data=None):
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
        else:
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
        reasons.extend(['尚无与本例当前输入绑定且已验收的最终 CFD 表面',
                        '尚无与最终表面绑定的合格体网格和 checkMesh 记录',
                        '患者阈值基准、出口压力口径和 K2 金标准仍待需求方裁定',
                        '本接口当前只实现非患者参考求解；患者求解适配尚未准入'])
        return {'id': case, 'label': case + ' · 鼻腔患者预览', 'kind': 'patient',
                'run_allowed': False, 'blocking_reasons': reasons,
                'geometry_status': geometry_status, 'mesh_status': 'not_admitted',
                'solver_status': 'not_admitted', 'artifacts': artifacts}

    def reference(self):
        checks = environment_checks(self.environment())
        checks.append({'name': 'reference_runner', 'passed': REFERENCE_SCRIPT.is_file(),
                       'source': 'work/07_cfd_pipeline/solver_reference/run_reference.py',
                       'detail': '复用已有真实 blockMesh/checkMesh/simpleFoam/foamToVTK 入口'})
        reasons = [c['name'] + '：' + str(c['detail']) for c in checks if not c['passed']]
        return {'id': 'reference_channel', 'label': '平行板气流参考 · 非患者', 'kind': 'reference',
                'run_allowed': not reasons, 'blocking_reasons': reasons,
                'geometry_status': 'runner_generated_reference', 'mesh_status': 'generated_on_new_run',
                'solver_status': 'available' if not reasons else 'environment_blocked',
                'artifacts': [], 'fixed_parameters': FIXED_PARAMETERS,
                'parameters': FIXED_PARAMETERS, 'recommended_settings': {'levels': ['coarse']}}

    def catalog(self):
        cases = [self.reference()]
        for case in EXISTING:
            if (self.review_root / case / 'landmarks.json').is_file():
                cases.append(self.patient(case))
        cases.extend(self.patient(data['id'], data) for data in self.case_manager.list())
        return {'schema': 'nasal_simulation_catalog/v1', 'cases': cases}

    def preflight(self, case, refresh=False):
        if case != 'reference_channel':
            item = self.patient(case)
            return {'passed': False, 'case_id': case, 'patient_data': True,
                    'source': '当前病例、boundary_review 与患者准入契约',
                    'checks': [{'name': 'patient_admission', 'passed': False,
                                'source': '当前病例版本与工作台患者适配实现',
                                'detail': reason} for reason in item['blocking_reasons']],
                    'blocking_reasons': item['blocking_reasons']}
        checks = environment_checks(self.environment(refresh))
        checks.append({'name': 'reference_runner', 'passed': REFERENCE_SCRIPT.is_file(),
                       'source': str(REFERENCE_SCRIPT.relative_to(ROOT)),
                       'detail': sha256(REFERENCE_SCRIPT) if REFERENCE_SCRIPT.is_file() else '求解入口缺失'})
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
        if action not in ('preflight', 'run_reference'):
            raise ValueError('action 只支持 preflight 或 run_reference')
        settings = payload.get('settings', {})
        if not isinstance(settings, dict) or set(settings) - {'levels'}:
            raise ValueError('参考参数固定；settings 仅支持 levels，不接受流量或压力覆盖')
        levels = settings.get('levels', ['coarse'])
        if (not isinstance(levels, list) or not levels or len(levels) > 3
                or any(level not in LEVELS for level in levels) or len(set(levels)) != len(levels)):
            raise ValueError('levels 仅支持不重复的 coarse、medium、fine')
        if case != 'reference_channel':
            item = self.patient(case)
            if action == 'run_reference':
                raise ValueError('患者运行拒绝：' + '；'.join(item['blocking_reasons']))
        with self.lock:
            if action == 'run_reference' and any(job['action'] == 'run_reference'
                                                and job['status'] not in TERMINAL for job in self.list()):
                raise ValueError('已有参考计算等待或运行中，请等待该任务结束')
            job_id = 's_' + uuid.uuid4().hex[:24]
            directory = self.directory(job_id)
            directory.mkdir(exist_ok=False)
            data = {'schema': 'nasal_simulation_job/v1', 'id': job_id, 'case_id': case,
                    'action': action, 'settings': {'levels': levels}, 'status': 'queued',
                    'stage': 'queued', 'created_at': now(), 'updated_at': now(),
                    'preflight': None, 'result': None, 'artifacts': [], 'error': None,
                    'exit_code': None, 'worker_pid': None, 'solver_pid': None,
                    'lock_root': str(self.case_manager.root), 'review_root': str(self.review_root),
                    'asset_paths': {}}
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
