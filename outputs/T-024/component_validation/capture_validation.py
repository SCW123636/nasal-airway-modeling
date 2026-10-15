"""Record exact component artifacts; this is not patient CFD acceptance."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import platform
import vtk
import numpy

root=Path(__file__).resolve().parents[3]
out=Path(__file__).resolve().parent
paths=['work/lib/patient_cfd_viewer.py','work/lib/test_patient_cfd_viewer.py',
       'work/07_cfd_pipeline/viewer/viewer.js','work/07_cfd_pipeline/viewer/index.html',
       'work/07_cfd_pipeline/viewer/viewer.css',
       'outputs/T-024/component_validation/make_fixture.py',
       'outputs/T-024/component_validation/check_viewer_fixture.cjs',
       'outputs/T-024/component_validation/unit-tests-final.log',
       'outputs/T-024/component_validation/presentation_verified/browser_fixture_results.json',
       'outputs/T-024/component_validation/presentation_verified/fixture_evidence.json',
       'outputs/T-024/component_validation/presentation_verified/scene-synthetic-internal-pressure.png',
       'outputs/T-024/component_validation/presentation_verified/desktop-synthetic-engineering-pressure.png',
       'outputs/T-024/component_validation/presentation_verified/mobile-320-synthetic-engineering.png',
       'outputs/T-024/component_validation/presentation_verified/mobile-390-synthetic-engineering.png']
browser=json.loads((out/'presentation_verified/browser_fixture_results.json').read_text(encoding='utf-8'))
assert len(browser['evidence'])==28 and all(check['passed'] for check in browser['evidence'])
assert 'Ran 3 tests' in (out/'unit-tests-final.log').read_text(encoding='utf-8')
binding={'recorded_at':datetime.now().astimezone().isoformat(),
    'scope':'synthetic_component_fixture_and_existing_display_regressions_only_not_patient_CFD_acceptance',
    'python':platform.python_version(),'numpy':numpy.__version__,'vtk':vtk.vtkVersion.GetVTKVersion(),
    'unit_tests':{'tests':3,'rejection_subcases':12,'result':'pass','log':'unit-tests-final.log'},
    'browser':{'checks':28,'result':'pass','base_url':'http://127.0.0.1:8769',
               'result_file':'presentation_verified/browser_fixture_results.json'},
    'sha256':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in paths}}
target=out/'validation_binding.json'
if target.exists():raise RuntimeError('Evidence binding exists; use a separate revision rather than overwrite')
target.write_text(json.dumps(binding,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'files':len(paths),'browser_checks':28,'unit_tests':3,'scope':binding['scope']},ensure_ascii=False))
