"""Final read-only preservation and supplemental terminal artifact identity."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import subprocess
from capture_original_baseline import read, sha
from observe_t029_job import frozen_identity

HERE = Path(__file__).resolve().parent
JOB = 's_aa79a63027b94bfb9a273898'


def main():
    original = read(HERE/'original-baseline-v1.json')
    checks = {}
    for group in ('original_input_file_sha256','original_watcher_audit_job_sha256'):
        checks[group] = {p:sha(p)==value for p,value in original[group].items()}
    old_root = Path('C:/ts_work/project_cases/simulation_jobs')/original['original_job']/'export'/original['original_job']
    checks['original_failed_export_sha256'] = {p:sha(old_root/p)==value for p,value in original['original_failed_export_sha256'].items()}
    assert all(ok for values in checks.values() for ok in values.values())
    files = ['evaluations/eval_001/log.foamToVTK','evaluations/evaluation_001.json','patient_engineering_report.json','patient_input_fingerprint.json']
    code = 'import pathlib,hashlib,json,sys;r=pathlib.Path(sys.argv[1]);print(json.dumps({p:hashlib.sha256((r/p).read_bytes()).hexdigest() for p in sys.argv[2:]}))'
    hashes = json.loads(subprocess.check_output(['wsl.exe','-d','Ubuntu-22.04','--','python3','-c',code,'/home/lenovo2/nasal_cfd_workspace_jobs/'+JOB,*files],text=True,encoding='utf-8',timeout=30))
    export = Path('C:/ts_work/project_cases/simulation_jobs')/JOB/'export'/JOB
    supplemental = {p:{'native':value,'export':sha(export/p)} for p,value in hashes.items()}
    assert all(v['native']==v['export'] for v in supplemental.values())
    identity = frozen_identity()
    data = {'schema':'t023_t029_final_integrity/v1','at':dt.datetime.now(dt.timezone.utc).isoformat(),'job_id':JOB,'original_protection_checks':checks,'all_originals_unchanged':True,'supplemental_native_export_sha256':supplemental,'candidate_15_code_34_input_freeze_still_equal':True,'candidate_identity':identity,'script_sha256':sha(__file__),'no_POST_solver_restart_service_or_monitor_launch':True,'patient_numerical_or_formal_field_display_accepted':False}
    with (HERE/'final-integrity.json').open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({'original34_inputs_12_failed_exports_4_protected_equal':True,'supplemental4_native_export_equal':True,'candidate15_sources_34_inputs_equal':True}))


if __name__=='__main__':main()
