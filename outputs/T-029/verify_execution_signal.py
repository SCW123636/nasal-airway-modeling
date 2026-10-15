"""Actual native subprocess exit fixture, not an OpenFOAM simulation."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
path = root / 'work/07_cfd_pipeline/solver/run_openfoam_case.py'
spec = importlib.util.spec_from_file_location('t029_executor_signal', path)
executor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor)
results = []
for expected, body in ((-8, 'import os,resource,signal; resource.setrlimit(resource.RLIMIT_CORE,(0,0)); print("SIGFPE fixture",flush=True); os.kill(os.getpid(),signal.SIGFPE)'),
                       (7, 'print("exit7 fixture",flush=True); raise SystemExit(7)')):
    with tempfile.TemporaryDirectory(prefix='t029_exit_fixture_', dir='/tmp') as tmp:
        try:
            executor.execute([sys.executable, '-c', body], Path(tmp), os.environ.copy(), 'log.fixture')
        except executor.CommandExecutionError as exc:
            assert exc.record['exit_code'] == expected, exc.record
            assert (Path(tmp) / 'log.fixture').read_text().strip()
            results.append({'expected':expected, 'actual':exc.record['exit_code'], 'passed':True,
                            'record':exc.record, 'log_text':(Path(tmp) / 'log.fixture').read_text()})
        else:
            raise AssertionError('failed subprocess did not raise')
print(json.dumps({'scope':'actual native Linux exit fixture; no CFD run', 'checks':results, 'passed':True}))
