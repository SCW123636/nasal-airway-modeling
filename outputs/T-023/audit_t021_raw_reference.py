"""Recompute reference facts from raw OpenFOAM artifacts, not diagnostics JSON."""
import hashlib, json, math, pathlib, re
from datetime import datetime, timezone
ROOT=pathlib.Path(__file__).resolve().parents[2]
OUT=pathlib.Path(__file__).resolve().parent
BASE=ROOT/'outputs/T-021/reference_split_run'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return p.read_text(encoding='utf-8-sig',errors='strict')
def rows(p):
    return [[float(t) for t in line.split()] for line in read(p).splitlines()
            if line.strip() and not line.lstrip().startswith('#')]
def patch(text,name):
    m=re.search(r'\b'+re.escape(name)+r'\s*\{([^{}]*)\}',text,re.S)
    assert m,name
    return m.group(1)
def close(a,b):assert math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-15),(a,b)

suite=json.loads(read(BASE/'feedback_suite_report.json'))
report={'at':datetime.now(timezone.utc).isoformat(),'scope':'raw new reference suite only; no patient result or service assertion',
        'command':'python outputs/T-023/audit_t021_raw_reference.py','scenarios':{},'artifact_sha256':{}}
for name in ['unequal','symmetric','swapped_labels']:
    original=suite['scenarios'][name]
    supplied=original['result']
    cases=[]
    for index,d in enumerate(sorted((BASE/name/'evaluations').glob('eval_*')),1):
        if not d.is_dir():continue
        manifest=json.loads(read(d/'run_manifest.json'))
        case_manifest=json.loads(read(d/'case_manifest.json'))
        status=json.loads(read(d/'run_status.json'))
        ev=json.loads(read(BASE/name/'evaluations'/('evaluation_%03d.json'%index)))
        assert manifest['case']==status['case']==ev['case']
        assert manifest['case'].startswith('/home/lenovo2/nasal_t021_split_20261015/'+name+'/evaluations/')
        assert manifest['execution_status']==status['status']=='completed'
        assert ev['exit_code']==0 and ev['status']=='accepted'
        assert [s['command'][0] for s in manifest['steps']]==['blockMesh','checkMesh','simpleFoam','foamToVTK']
        assert all(s['exit_code']==0 and s['elapsed_seconds']>0 for s in manifest['steps'])
        assert manifest['started_at'][:10]=='2026-10-15' and manifest['finished_at'][:10]=='2026-10-15'
        assert manifest['case_manifest']==case_manifest
        p,u=read(d/'0/p'),read(d/'0/U')
        assert re.search(r'dimensions\s*\[0 2 -2 0 0 0 0\]',p)
        assert re.search(r'dimensions\s*\[0 1 -1 0 0 0 0\]',u)
        rho=case_manifest['physics']['rho_kg_m3'];pressure=ev['pressure_pa']
        for inlet in ['inlet_L','inlet_R']:
            b=patch(p,inlet); assert 'fixedValue' in b
            close(float(re.search(r'value\s+uniform\s+([^;]+)',b).group(1))*rho,pressure)
            assert 'pressureInletOutletVelocity' in patch(u,inlet)
        assert float(re.search(r'value\s+uniform\s+([^;]+)',patch(p,'outlet')).group(1))==0
        assert 'zeroGradient' in patch(u,'outlet')
        assert not any(t in p+u for t in ['flowRateInletVelocity','volumetricFlowRate','massFlowRate'])
        assert case_manifest['boundary']=={'mode':'common_inlet_pressure_feedback',
            'inlet_static_pressure_Pa_gauge':pressure,'outlet_static_pressure_Pa_gauge':0.,
            'target_role':'outer_iteration_objective_not_simultaneous_PDE_flow_boundary'}
        log=read(d/'log.simpleFoam');meshlog=read(d/'log.checkMesh')
        assert 'OpenFOAM' in log and 'simpleFoam' in log and manifest['case'] in log
        assert 'Mesh OK.' in meshlog and not re.search(r'Failed\s+\d+\s+mesh checks',meshlog)
        assert re.search(r'(?m)^End\s*$',log) and 'FOAM FATAL' not in log
        time=float(re.findall(r'(?m)^Time = (\S+)',log)[-1])
        last_time_marker=list(re.finditer(r'(?m)^Time = (\S+)',log))[-1]
        last_block=log[last_time_marker.start():]
        residuals={f:float(v) for f,v in re.findall(r'Solving for (\w+), Initial residual = ([\deE+.-]+)',last_block)}
        linear_final={f:float(v) for f,v in re.findall(r'Solving for (\w+), Initial residual = [\deE+.-]+, Final residual = ([\deE+.-]+)',last_block)}
        assert {'Ux','Uy','p'}<=residuals.keys()
        residual_max=max(residuals.values());assert residual_max<=1e-5
        continuity=float(re.findall(r'global = ([\deE+.-]+)',last_block)[-1]);assert abs(continuity)<=1e-6
        phi={};pobs={};sample_times=[]
        for label in ['inlet_L','inlet_R','outlet']:
            fr=rows(d/('postProcessing/flow_'+label+'/0/surfaceFieldValue.dat'))
            pr=rows(d/('postProcessing/pressure_'+label+'/0/surfaceFieldValue.dat'))
            assert len(fr)>100 and len(pr)>100
            assert fr[-1][0]==pr[-1][0]==time
            assert [r[0] for r in fr]==[r[0] for r in pr]
            sample_times.append([r[0] for r in fr])
            phi[label]=fr[-1][1];pobs[label]=pr[-1][1]*rho
            close(pobs[label],pressure if label!='outlet' else 0.)
        assert sample_times[0]==sample_times[1]==sample_times[2]
        assert phi['inlet_L']<0 and phi['inlet_R']<0 and phi['outlet']>0
        ql,qr,qo=-phi['inlet_L'],-phi['inlet_R'],phi['outlet'];qt=ql+qr
        imbalance=abs(qt-qo)/qt;assert imbalance<=.005
        close(ql,ev['evaluation']['q_left_m3_s']);close(qr,ev['evaluation']['q_right_m3_s']);close(qo,ev['evaluation']['q_out_m3_s'])
        close(imbalance,ev['evaluation']['mass_imbalance_frac'])
        for label in ['0/p','0/U','case_manifest.json','run_manifest.json','run_status.json','log.simpleFoam','log.checkMesh','execution.log']:
            report['artifact_sha256'][str((d/label).relative_to(BASE)).replace('\\','/')]=sha(d/label)
        for label in ['inlet_L','inlet_R','outlet']:
            for field in ['flow','pressure']:
                file=d/('postProcessing/'+field+'_'+label+'/0/surfaceFieldValue.dat')
                report['artifact_sha256'][str(file.relative_to(BASE)).replace('\\','/')]=sha(file)
        cases.append({'case':str(d.relative_to(BASE)),'native_case':manifest['case'],'pressure_pa':pressure,
          'q_left_m3_s':ql,'q_right_m3_s':qr,'q_out_m3_s':qo,'q_total_m3_s':qt,
          'left_fraction':ql/qt,'mass_imbalance_frac':imbalance,'residual_max':residual_max,
          'linear_final_residuals':linear_final,'continuity_global':continuity,'time':time,
          'started_at':manifest['started_at'],'finished_at':manifest['finished_at'],
          'step_exit_codes':[s['exit_code'] for s in manifest['steps']]})
    assert len(cases)==supplied['evaluation_count']==len(supplied['iterations'])
    assert [x['pressure_pa'] for x in cases]==[x['pressure_pa'] for x in supplied['iterations']]
    final=next(x for x in cases if x['pressure_pa']==supplied['pressure_pa'])
    for k in ['q_total_m3_s','q_left_m3_s','q_right_m3_s','q_out_m3_s','left_fraction']:close(final[k],supplied[k])
    target=supplied['target_m3_s'];close(target,1/60000)
    error=abs(final['q_total_m3_s']-target)/target;assert error<=.01
    report['scenarios'][name]={'evaluations':cases,'final':final,'target_m3_s':target,'relative_error':error}
u,s,w=[report['scenarios'][k]['final'] for k in ['unequal','symmetric','swapped_labels']]
assert u['left_fraction']>.6
assert abs(s['left_fraction']-.5)<.01
assert abs(u['left_fraction']+w['left_fraction']-1)<1e-9
close(u['pressure_pa'],w['pressure_pa']);close(u['q_total_m3_s'],w['q_total_m3_s'])
report['passed']=True
target=OUT/'t021_raw_reference_result.json';assert not target.exists();target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':True,'evaluation_count':sum(len(x['evaluations']) for x in report['scenarios'].values()),
                 'summary':{k:{x:v['final'][x] for x in ['pressure_pa','q_total_m3_s','left_fraction']} for k,v in report['scenarios'].items()}},ensure_ascii=False))
