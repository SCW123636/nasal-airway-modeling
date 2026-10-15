"""Read real package; use isolated Windows workdir so native guard stops solver."""
import hashlib,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[2];OUT=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'work/lib'))
import patient_cfd_runner
SOURCE=ROOT/'work/lib/patient_cfd_runner.py'
source_sha=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
folder=pathlib.Path('C:/ts_work/project_cases/patient_cfd_inputs/b15_engineering')
work=OUT/'patient_resume_probe_attempt1';work.mkdir(exist_ok=False)
file=work/'patient_input_fingerprint.json'
before={'admission_sha256':'0'*64,'config_sha256':'0'*64}
file.write_text(json.dumps(before,indent=2),encoding='utf-8')
try:
    patient_cfd_runner.run(folder,work)
except Exception as exc:
    error={'type':type(exc).__name__,'message':str(exc)}
else:raise AssertionError('Native Windows guard unexpectedly did not stop')
after=json.loads(file.read_text(encoding='utf-8'))
report={'source_sha256':source_sha,'command':'python outputs/T-023/probe_patient_resume_fingerprint.py',
        'scope':'isolated Windows guard probe; real b15 input package read-only, no solver, no synthetic CFD result',
        'before':before,'after':after,'error':error,'old_fingerprint_overwritten':before!=after,
        'solver_started':False,'failure_condition':'Old patient input fingerprint must be compared and refused before any replacement'}
target=OUT/'patient_resume_probe_attempt1.json';assert not target.exists();target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
