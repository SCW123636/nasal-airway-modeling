"""Rerun only the two preserved failed-step subtests in an approved ASCII root."""
from pathlib import Path
import contextlib
import datetime as dt
import hashlib
import json
import os
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ASCII_ROOT = Path(r'C:\ts_work\t023_failed_exit_control_20261015')
TEST = 'test_run_openfoam_case.SolverEngineeringTests.test_failed_command_records_real_bottom_exit_and_stops_before_vtk'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    assert str(ASCII_ROOT).isascii()
    assert ASCII_ROOT.resolve() == Path(r'C:\ts_work\t023_failed_exit_control_20261015')
    ASCII_ROOT.mkdir(exist_ok=False)
    tempfile.tempdir = str(ASCII_ROOT)
    os.environ['TMP'] = os.environ['TEMP'] = str(ASCII_ROOT)
    sys.path.insert(0, str(ROOT / 'work/lib'))
    paths = [ROOT / 'work/lib/test_run_openfoam_case.py', ROOT / 'work/07_cfd_pipeline/solver/run_openfoam_case.py']
    before = {str(p): sha(p) for p in paths}
    with (HERE / 'failed-exit-ascii-control.log').open('x', encoding='utf-8') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName(TEST))
    assert before == {str(p): sha(p) for p in paths}
    data = {
        'at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'test': TEST,
        'run_count': result.testsRun,
        'subtest_exit_codes': [-8, 7],
        'failures': len(result.failures),
        'errors': len(result.errors),
        'successful': result.wasSuccessful(),
        'ascii_temp_root': str(ASCII_ROOT),
        'authorization': 'Lead explicit 2026-10-15 message: create ASCII temporary root and rerun only the failed-step control, preserving first failure.',
        'source_sha256': before,
        'script_sha256': sha(__file__),
        'original_failure': 'targeted-contract-tests.json and targeted-contract-tests.log retained unchanged',
        'scope': 'Mocked failed-command metadata only; no actual CFD, POST, service action, or complete-suite rerun.'
    }
    with (HERE / 'failed-exit-ascii-control.json').open('x', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(json.dumps(data, ensure_ascii=False))
    assert result.wasSuccessful()


if __name__ == '__main__':
    main()
