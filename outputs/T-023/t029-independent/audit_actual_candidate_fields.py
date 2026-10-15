"""Independently check this candidate's raw cells, served bytes and cut vertices."""
from pathlib import Path
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import traceback
import urllib.request

os.environ['OMP_NUM_THREADS'] = os.environ['OPENBLAS_NUM_THREADS'] = os.environ['MKL_NUM_THREADS'] = '1'
import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

vtk.vtkMultiThreader.SetGlobalMaximumNumberOfThreads(1)
HERE = Path(__file__).resolve().parent
JOB = 's_aa79a63027b94bfb9a273898'
CASE = 'b15_engineering_t029a'
ROOT = Path('C:/ts_work/project_cases/simulation_jobs') / JOB
EVAL = ROOT / 'export' / JOB / 'evaluations/eval_001'
BASE = 'http://127.0.0.1:8769'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def remote_sha(url):
    value = hashlib.sha256()
    with urllib.request.urlopen(BASE + url, timeout=60) as response:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            value.update(block)
    return value.hexdigest()


def raw_internal(path, kind, dim):
    text = path.read_text(encoding='ascii')
    match = re.search(r'dimensions\s*\[([^]]+)\]', text)
    assert [int(x) for x in match[1].split()] == dim
    match = re.search(r'internalField\s+nonuniform\s+List<' + kind + r'>\s+(\d+)\s*\(', text)
    assert match, 'Expected real nonuniform raw field'
    body = text[match.end():text.index('boundaryField', match.end())].strip()
    body = re.sub(r'\)\s*;\s*$', '', body)
    values = np.fromstring(body.replace('(', ' ').replace(')', ' '), sep=' ')
    assert values.size == int(match[1]) * (3 if kind == 'vector' else 1)
    assert np.isfinite(values).all()
    return values.reshape(-1, 3) if kind == 'vector' else values


def run():
    identity = read(HERE / 'terminal-native-identity.json')
    assert identity['native_export_all_equal']
    current = identity['actual_native']
    assert current['latest_field_time'] == '120' and current['End'] and not current['SIMPLE_convergence']
    sources = list((EVAL / 'VTK').rglob('internal.vtu'))
    assert len(sources) == 1
    source = sources[0]
    mesh = read(ROOT / 'viewer_mesh.json')
    manifest = read(ROOT / 'viewer.json')
    config = read(EVAL / 'config.json')
    pv = mesh['result']['provenance']
    assert pv['field_time'] == '120' and pv['evaluation'] == 'eval_001'
    assert pv['native_case'] == current['native_case']
    assert len(mesh['interior_slices']) == 3 and {s['axis'] for s in mesh['interior_slices']} == {'x', 'y', 'z'}
    assert pv['p_file_sha256'] == sha(EVAL / '120/p')
    assert pv['U_file_sha256'] == sha(EVAL / '120/U')
    assert pv['source_vtu_sha256'] == sha(source)
    reader = vtk.vtkXMLUnstructuredGridReader()
    reader.SetFileName(str(source)); reader.Update(); grid = reader.GetOutput()
    raw_checks = {}
    for name, kind, dimensions in [('p', 'scalar', [0,2,-2,0,0,0,0]), ('U', 'vector', [0,1,-1,0,0,0,0])]:
        expected = raw_internal(EVAL / ('120/' + name), kind, dimensions)
        array = grid.GetCellData().GetArray(name)
        assert array is not None, 'Raw native cell association unavailable: ' + name
        actual = vtk_to_numpy(array).astype(float)
        assert len(expected) == grid.GetNumberOfCells() == 1161194
        np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=1e-6)
        raw_checks[name] = {'native_export_raw_sha256': sha(EVAL / ('120/' + name)), 'cell_count': len(expected), 'max_abs_difference': float(np.max(np.abs(actual-expected))), 'tolerance': 'VTK ascii serialization rtol1e-5, atol1e-6', 'dimensions': dimensions}
    del grid, reader
    helper_path = HERE.parent / 'audit_patient_field_arrays.py'
    spec = importlib.util.spec_from_file_location('t023_independent_field_arrays', helper_path)
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    audit = helper.audit(mesh, manifest, source, config, JOB, CASE)
    served = {}
    for url, local in [('/simulation-assets/' + JOB + '/viewer.json', ROOT / 'viewer.json'), ('/simulation-assets/' + JOB + '/viewer_mesh.json', ROOT / 'viewer_mesh.json'), (pv['source_vtu_url'], source), ('/simulation-assets/' + JOB + '/patient-final-config.json', EVAL / 'config.json')]:
        served[url] = {'served': remote_sha(url), 'local': sha(local)}
        assert served[url]['served'] == served[url]['local']
    return {'schema': 't023_t029_actual_field_audit/v1', 'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'job_id': JOB, 'case_id': CASE, 'field_time': '120', 'raw_cell_field_checks': raw_checks, 'surface_and_independent_volume_probe': audit, 'served_byte_identity': served, 'helper_sha256': sha(helper_path), 'script_sha256': sha(__file__), 'passed': True, 'scope': 'Field identity, units, LPS coordinates, actual served bytes and three interior cuts; no numerical/convergence/clinical acceptance.'}


if __name__ == '__main__':
    try:
        value = run()
    except Exception:
        value = {'passed': False, 'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'failure': traceback.format_exc(), 'script_sha256': sha(__file__)}
        with (HERE / 'actual-field-audit-first-failure.json').open('x', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
        raise
    with (HERE / 'actual-field-audit.json').open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')
    print(json.dumps(value, ensure_ascii=False))
