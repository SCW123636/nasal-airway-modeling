"""Persist synthetic component fixtures; never register with the job API."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parent
OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'work/lib'))
from test_patient_cfd_viewer import fixture
from patient_cfd_viewer import export_patient_trial_viewer

directory=OUT/'synthetic_job'
directory.mkdir(exist_ok=True)
if (directory/'viewer.json').exists():raise RuntimeError('Fixture evidence already exists; use an isolated new directory')
base,source,report,data,asset,points,u,p=fixture(directory)
viewing=export_patient_trial_viewer(directory,report,asset,data)
viewer=json.loads((directory/'viewer.json').read_text(encoding='utf-8'))
viewer['cases'][0]['label']='合成VTU组件测试（非患者计算）'
viewer['cases'][0]['note']='已知答案合成文件，仅验证导出与页面；不代表真实患者求解。 '+viewer['cases'][0]['note']
(directory/'viewer.json').write_text(json.dumps(viewer,ensure_ascii=False),encoding='utf-8')
(OUT/'fixture_evidence.json').write_text(json.dumps({'kind':'synthetic_component_fixture_not_patient_solver',
    'expected_points_mm':(points*1000).tolist(),'expected_U_m_s':u.tolist(),'expected_p_Pa':(p*1.25).tolist(),
    'export_result':viewing,'job_state':data,'report':report},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(viewing,ensure_ascii=False))
