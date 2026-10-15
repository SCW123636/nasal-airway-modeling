"""Read real frozen package through the real manager, without a solver/job POST."""
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'work/lib'))
from ct_case_pipeline import CaseManager
from cfd_workspace_jobs import SimulationJobs

with tempfile.TemporaryDirectory(prefix='t029_manager_read_') as tmp:
    root = Path(tmp)
    cases = CaseManager(root / 'cases')
    try:
        (root / 'reviews').mkdir()
        manager = SimulationJobs(cases, root / 'reviews', root / 'jobs')
        manager.patient_input_root = Path('C:/ts_work/project_cases/patient_cfd_inputs')
        name = 'b15_engineering_t029a'
        binding = manager.patient_source_binding(name)
        catalog = manager.catalog()
        selected = next(item for item in catalog['cases'] if item['id'] == name)
        preflight = manager.preflight(name)
        record = {'scope':'actual frozen package and production manager; actual environment probe; no run POST/solver',
                  'source_binding':binding, 'catalog_case':selected, 'preflight':preflight}
        assert binding is None
        assert selected['run_allowed'] and selected['clinical_validation'] == 'not_validated'
        assert preflight['passed'], preflight
        assert not list((root / 'jobs').glob('s_*'))
        path = Path(__file__).with_name('real-manager-package-check.json')
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({'passed':True, 'case_id':name, 'preflight_passed':True, 'source_binding':binding, 'jobs_created':0}))
    finally:
        cases.pool.shutdown(wait=True)
