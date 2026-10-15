"""T023 T029 service reload: execute only after Lead's specific freeze notification.

Preserves the old reload script/evidence. Requires a new immutable T023 contract.
Uses GET only, verifies two ports/process identities, and never submits a job.
"""
from __future__ import annotations
import argparse
import base64
import ctypes
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE/'service-reload'
BASE = 'http://127.0.0.1:8769'
EXPECTED_CASE = 'b15_engineering_t029a'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_once(name, value):
    with (OUT/name).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def powershell(code):
    code = '[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new();'+code
    encoded = base64.b64encode(code.encode('utf-16-le')).decode('ascii')
    return subprocess.check_output(['powershell.exe','-NoProfile','-EncodedCommand',encoded],
                                   creationflags=subprocess.CREATE_NO_WINDOW).decode('utf-8-sig').strip()


def get(path, *, binary=False):
    assert path.startswith('/') and not path.startswith('//')
    with urllib.request.urlopen(BASE+path, timeout=10) as response:
        data = response.read()
    return data if binary else json.loads(data)


def listener(port):
    assert port in (8769,8774)
    code = "$n=@(Get-NetTCPConnection -State Listen -LocalPort "+str(port)+" -ErrorAction Stop); if($n.Count -ne 1 -or $n[0].LocalAddress -ne '127.0.0.1'){throw 'unexpected listeners'}; $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$n[0].OwningProcess); [pscustomobject]@{pid=$p.ProcessId;exe=$p.ExecutablePath;cmdline=$p.CommandLine;parent_pid=$p.ParentProcessId;create_time=$p.CreationDate.ToUniversalTime().ToString('o')} | ConvertTo-Json -Compress"
    return json.loads(powershell(code))


def argv_windows(command):
    count = ctypes.c_int()
    parse = ctypes.windll.shell32.CommandLineToArgvW
    parse.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    parse.restype = ctypes.POINTER(ctypes.c_wchar_p)
    pointer = parse(command, ctypes.byref(count))
    if not pointer:
        raise ctypes.WinError()
    try:
        return [pointer[i] for i in range(count.value)]
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(ctypes.cast(pointer, ctypes.c_void_p))


def option(argv, name):
    assert argv.count(name) <= 1, ('duplicate option', name)
    if name not in argv:
        return None
    i = argv.index(name)
    assert i+1 < len(argv)
    return argv[i+1]


def frozen_contract(path):
    path = Path(path).resolve()
    assert path.is_relative_to(HERE), 'reload contract must be T023-owned'
    c = json.loads(path.read_text(encoding='utf-8'))
    assert c['schema'] == 't023_t029_service_reload_contract/v1'
    assert Path(c['project_root']).resolve() == ROOT
    assert c['case_id'] == EXPECTED_CASE
    assert c['lead_execution_authorization'].strip(), 'specific Lead execution notice required'
    freeze = Path(c['freeze_artifact']['path']).resolve()
    assert sha(freeze) == c['freeze_artifact']['sha256'], 'producer freeze artifact changed'
    files = c['frozen_file_sha256']
    assert files and any(Path(p).resolve() == ROOT/'work/lib/patient_cfd_admission.py' for p in files)
    assert any(Path(p).resolve() == ROOT/'work/lib/serve_cfd_workspace.py' for p in files)
    for p, expected in files.items():
        assert Path(p).is_absolute(), ('freeze path must be absolute', p)
        assert sha(p) == expected, ('frozen source/input changed', p)
    return c


def no_active_work():
    jobs = get('/api/simulation/jobs')['jobs']
    active = [x for x in jobs if x['status'] in ['queued','running']]
    assert not active, ('active API jobs: no reload', active)
    code = "$p=@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -match '\\\\python(?:w)?[.]exe$' -and $_.CommandLine -match 'cfd_workspace_jobs[.]py.+--worker'} | Select-Object ProcessId,ExecutablePath,CommandLine); ConvertTo-Json -InputObject $p -Compress"
    workers = json.loads(powershell(code) or '[]')
    assert not workers, ('active job workers: no reload', workers)
    return {'active_jobs': active, 'workers': workers, 'job_count': len(jobs)}


def verify_project_service(identity):
    argv = argv_windows(identity['cmdline'])
    assert Path(argv[0]).resolve() == Path(identity['exe']).resolve(), 'executable/argv mismatch'
    service = ROOT/'work/lib/serve_cfd_workspace.py'
    assert sum(Path(arg).resolve() == service for arg in argv if arg.lower().endswith('.py')) == 1
    assert option(argv, '--port') == '8769'
    return argv


def same_process(a, b):
    return all(a[key] == b[key] for key in ['pid','create_time','exe','cmdline'])


def main(contract_path):
    contract_path = Path(contract_path).resolve()
    contract = frozen_contract(contract_path)
    OUT.mkdir(exist_ok=False)
    report = {'at': datetime.now(timezone.utc).isoformat(), 'script_sha256': sha(__file__),
              'project_root': str(ROOT), 'contract_path': str(contract_path), 'contract_sha256': sha(contract_path),
              'contract': contract, 'no_job_submission': True, 'shortcut_opened': False}
    try:
        before = listener(8769)
        other = listener(8774)
        command = verify_project_service(before)
        health = get('/health.json')
        assert health['service'] == 'nasal-cfd-local-workspace/v1'
        static = {}
        for name in ['simulation.js','workspace.js']:
            served = get('/workspace/'+name, binary=True)
            local = (ROOT/'work/07_cfd_pipeline/workspace'/name).read_bytes()
            assert served == local, ('served/static project identity mismatch', name)
            static[name] = hashlib.sha256(served).hexdigest()
        quiet = no_active_work()
        report.update(old_8769=before, preserved_8774=other, health_before=health,
                      quiet_before=quiet, static_sha256=static, command=command,
                      preserved_case_root=option(command, '--case-root'))
        write_once('before.json', report)
        # Recheck immediately before the only destructive action. All of these are reads.
        assert same_process(listener(8769), before)
        assert same_process(listener(8774), other)
        no_active_work()
        frozen_contract(contract_path)
        expected = json.dumps(before, ensure_ascii=False).replace("'", "''")
        stop = "$e=ConvertFrom-Json '"+expected+"'; $n=@(Get-NetTCPConnection -State Listen -LocalPort 8769 -ErrorAction Stop); if($n.Count -ne 1 -or $n[0].LocalAddress -ne '127.0.0.1' -or $n[0].OwningProcess -ne $e.pid){throw 'listener changed'}; $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$e.pid); if($p.CreationDate.ToUniversalTime().ToString('o') -ne $e.create_time -or $p.ExecutablePath -ne $e.exe -or $p.CommandLine -ne $e.cmdline){throw 'process identity changed'}; Stop-Process -Id $e.pid -ErrorAction Stop"
        powershell(stop)
        write_once('old_process_stopped.json', {'at': datetime.now(timezone.utc).isoformat(), 'verified_old_8769': before})
        with (OUT/'stdout.log').open('xb') as log:
            process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_NO_WINDOW)
        write_once('launch.json', {'at': datetime.now(timezone.utc).isoformat(), 'launcher_pid': process.pid,
                                  'command': command, 'cwd': str(ROOT), 'hidden': True})
        for _ in range(60):
            try:
                after_health = get('/health.json')
                after = listener(8769)
                if after_health['service'] == 'nasal-cfd-local-workspace/v1' and after['pid'] != before['pid']:
                    break
            except (OSError, AssertionError, subprocess.SubprocessError):
                pass
            time.sleep(.25)
        else:
            raise RuntimeError('8769 did not return healthy; no automatic second reload')
        assert verify_project_service(after) == command, 'restarted command changed'
        assert same_process(listener(8774), other), '8774 identity changed'
        for name in static:
            assert hashlib.sha256(get('/workspace/'+name, binary=True)).hexdigest() == static[name]
        quiet_after = no_active_work()
        catalog = get('/api/simulation/catalog')
        ids = [x['id'] for x in catalog['cases']]
        assert EXPECTED_CASE in ids, 'new frozen admission version absent after reload'
        frozen_contract(contract_path)
        report.update(new_8769=after, health_after=after_health, quiet_after=quiet_after,
                      catalog_case_ids=ids, preserved_8774_after=listener(8774), passed=True)
        write_once('result.json', report)
        print(json.dumps({'passed': True, 'old_pid': before['pid'], 'new_pid': after['pid'],
                          'preserved_8774_pid': other['pid'], 'case_id': EXPECTED_CASE}, ensure_ascii=False))
    except Exception as exc:
        report.update(passed=False, exception=repr(exc))
        write_once('failure.json', report)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true', required=True)
    parser.add_argument('--contract', type=Path, required=True)
    arguments = parser.parse_args()
    main(arguments.contract)
