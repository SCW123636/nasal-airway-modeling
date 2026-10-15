"""Replay only eight T029 contract regressions, with all temporary writes here."""
from pathlib import Path
import ast
import contextlib
import datetime as dt
import hashlib
import json
import os
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'work/lib'))
TARGETS={
 'test_patient_cfd_admission':[
  'test_versioned_sample_retains_origin_and_strict_frozen_sources',
  'test_versioned_sample_mismatched_origin_refuses_admission_and_authority',
  'test_unrecognized_engineering_suffix_and_wrong_version_refuse'],
 'test_run_openfoam_case':[
  'test_failed_command_records_real_bottom_exit_and_stops_before_vtk',
  'test_real_subprocess_nonzero_is_not_replaced_with_outer_exit',
  'test_launch_error_has_unknown_exit_and_actual_command_log'],
 'test_cfd_workspace_jobs':[
  'test_versioned_engineering_catalog_preflight_and_source_binding_use_real_admission',
  'test_versioned_engineering_bad_origin_and_changed_source_still_block']}


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    temporary=HERE/'targeted-test-temp';temporary.mkdir(exist_ok=False)
    tempfile.tempdir=str(temporary);os.environ['TMP']=os.environ['TEMP']=str(temporary)
    names=[];sources={}
    for module,methods in TARGETS.items():
        p=ROOT/'work/lib'/(module+'.py');tree=ast.parse(p.read_text(encoding='utf-8'));sources[str(p)]=sha(p)
        for method in methods:
            classes=[c.name for c in tree.body if isinstance(c,ast.ClassDef) and any(isinstance(m,ast.FunctionDef) and m.name==method for m in c.body)]
            assert len(classes)==1;names.append(module+'.'+classes[0]+'.'+method)
    with (HERE/'targeted-contract-tests.log').open('x',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        suite=unittest.defaultTestLoader.loadTestsFromNames(names)
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    assert all(sha(p)==h for p,h in sources.items())
    data={'at':dt.datetime.now(dt.timezone.utc).isoformat(),'tests':names,'test_source_sha256':sources,'run_count':result.testsRun,
          'failures':len(result.failures),'errors':len(result.errors),'successful':result.wasSuccessful(),
          'scope':'Eight targeted version/admission/failed-exit regressions; real exit7 child and synthetic -8 records; no CFD/service/production jobs.',
          'script_sha256':sha(__file__)}
    with (HERE/'targeted-contract-tests.json').open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps(data,ensure_ascii=False));assert result.wasSuccessful()


if __name__=='__main__':main()
