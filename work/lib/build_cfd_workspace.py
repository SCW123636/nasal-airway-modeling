"""Assemble actual patient previews and a separately labelled analytic reference."""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np

from cfd_contract import validate_result
from coarse_localization_summary import summarize_localization

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT/'work'/'07_cfd_pipeline'


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')


def analytic_pipe():
    """A longitudinal midplane of an ideal circular pipe; analytic, never a CFD solve."""
    radius_m, length_m, q_m3_s = .002, .06, 1e-3/60
    rho, mu = 1.2, 1.81e-5
    mean_u = q_m3_s/(np.pi*radius_m**2)
    dp = 8*mu*length_m*q_m3_s/(np.pi*radius_m**4)
    xx, zz = np.meshgrid(np.linspace(-radius_m,radius_m,41), np.linspace(0,length_m,81))
    velocity = 2*mean_u*(1-(xx.ravel()/radius_m)**2)
    points = np.column_stack([1000*xx.ravel(), np.zeros(xx.size),1000*zz.ravel()])
    vectors = np.column_stack([np.zeros(xx.size),np.zeros(xx.size),velocity])
    pressure = dp*(1-zz.ravel()/length_m)
    faces=[]
    for z in range(80):
        for x in range(40):
            a=z*41+x; b=a+1; c=a+41; d=c+1
            faces.extend([[a,b,d],[a,d,c]])
    result={'schema':'nasal_cfd_result/v1','type':'analytic_reference',
            'geometry':{'kind':'idealized','case_id':None}, 'clinical_validation':'not_validated',
            'physics':{'turbulence_model':'laminar','rho_kg_m3':rho,'mu_Pa_s':mu},
            'provenance':{'method':'analytic_solution',
                'equation':'u_z(r)=2Q/(pi R^2)*(1-r^2/R^2); p(z)=8 mu Q*(L-z)/(pi R^4)',
                'note':'Fully developed ideal circular pipe, analytic reference only, not numerical CFD or a patient'},
            'parameters':{'radius_mm':2.,'length_mm':60.,'flow_L_min':1.,
                          'pressure_drop_Pa':float(dp),'mean_velocity_m_s':float(mean_u),
                          'reynolds':float(rho*mean_u*2*radius_m/mu)},
            'fields':{'velocity':{'unit':'m/s','association':'point','values':vectors.tolist()},
                      'pressure':{'unit':'Pa','association':'point','values':pressure.tolist(),
                                  'quantity':'static','reference':'gauge','source_unit':'Pa','source_field':'p'},
                      'turbulence_intensity':None},
            'turbulence_intensity_status':'not_applicable'}
    checked=validate_result(result)
    if not checked['valid']:
        raise ValueError(checked['errors'])
    obj={'schema':'candidate_surface_preview/v1','case':None,'status':'analytic_reference',
         'display_geometry_only':True,'review_required':False,'cfd_ready':False,
         'coordinate_system':'synthetic_Cartesian','unit':'mm',
         'geometry':{'vertices':points.ravel().tolist(),'indices':np.asarray(faces).ravel().tolist(),
                     'bounds_lps_mm':{'min':points.min(0).tolist(),'max':points.max(0).tolist()}},
         'result':result,'qc':{'reference_check':checked}}
    write_json(BASE/'reference'/'pipe_analytic'/'viewer_mesh.json',obj)
    write_json(BASE/'reference'/'pipe_analytic'/'result.json',result)
    return {'id':'analytic_pipe','label':'参考算例 · 圆管解析解','type':'analytic_reference',
            'mesh_url':'../reference/pipe_analytic/viewer_mesh.json',
            'note':'1 L/min，半径 2 mm，长度 60 mm；解析计算值，用于核对展示与单位。',
            'landmarks':[]}


def main():
    feedback_path = ROOT/'work'/'06_auto_landmarks'/'feedback_review'/'audit.json'
    if feedback_path.is_file():
        audit = json.loads(feedback_path.read_text(encoding='utf-8'))
        if audit.get('schema') != 'landmark_feedback_audit/v1' or audit.get('coordinate_system') != 'LPS' or audit.get('unit') != 'mm':
            raise ValueError('feedback audit identity or units are invalid')
        feedback_audit = {
            'status': 'diagnostic_review_complete',
            'source': '06_auto_landmarks/feedback_review/audit.json',
            'source_sha256': __import__('hashlib').sha256(feedback_path.read_bytes()).hexdigest(),
            'observations': len(audit.get('feedback', [])),
            'matched_current_proposals': sum(bool(item.get('bound_to_current_proposal')) for item in audit.get('feedback', [])),
            'unresolved_or_mismatched': sum(not bool(item.get('bound_to_current_proposal')) for item in audit.get('feedback', [])),
            'original_proposals_unchanged': bool(audit.get('input_integrity_verified')),
            'review_url': '/landmark-review/feedback_review/index.html',
            'clinical_acceptance': False,
        }
    else:
        feedback_audit = {
            'status': 'not_generated', 'source': None, 'source_sha256': None,
            'observations': 0, 'matched_current_proposals': 0, 'unresolved_or_mismatched': 0,
            'original_proposals_unchanged': None,
            'review_url': '/landmark-review/feedback_review/index.html',
            'clinical_acceptance': False,
        }
    cases=[]
    for case,label in [('p0','病例 0'),('p1','病例 1'),('p2','病例 2'),
                       ('p3','病例 3 · t2'),('p3t1','病例 3 · t1')]:
        mesh=BASE/'preview'/case/'viewer_mesh.json'
        if not mesh.is_file():
            continue
        data=json.loads(mesh.read_text(encoding='utf-8'))
        if (data.get('schema')!='candidate_surface_preview/v1' or data.get('case')!=case
                or data.get('coordinate_system')!='LPS' or data.get('unit')!='mm'
                or data.get('status')!='unreviewed_candidate_preview'):
            raise ValueError('Patient preview identity, status or LPS/mm coordinate metadata mismatch')
        if data.get('cfd_ready') is not False or data.get('display_geometry_only') is not True:
            raise ValueError('Patient preview must explicitly be non-CFD display geometry')
        if data.get('result') is not None:
            embedded=data['result']
            if (embedded.get('type')!='patient_preview'
                    or embedded.get('geometry',{}).get('case_id')!=case
                    or not validate_result(embedded)['valid']):
                raise ValueError('Patient mesh contains foreign or invalid result fields')
        lm_path=ROOT/'work'/'06_auto_landmarks'/case/'landmarks.json'
        lm=json.loads(lm_path.read_text(encoding='utf-8'))
        if lm.get('case')!=case or lm.get('coordinate_system')!='LPS' or lm.get('unit')!='mm':
            raise ValueError('Landmark case identity and LPS/mm units must match the patient mesh')
        for point in lm.get('landmarks',{}).values():
            for field in ('point_lps_mm','normal_lps'):
                value=point.get(field)
                if value is not None and (not isinstance(value,list) or len(value)!=3 or
                        any(isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v) for v in value)):
                    raise ValueError('Landmark coordinates and normals require three finite non-boolean numbers')
        lm_affine=lm.get('source_geometry',{}).get('affine_4x4_LPS')
        if lm_affine is not None and not np.allclose(lm_affine,data['affine_4x4_LPS'],rtol=0,atol=1e-5):
            raise ValueError('Landmark and preview source geometry do not match')
        result={'schema':'nasal_cfd_result/v1','type':'patient_preview',
                'geometry':{'kind':'patient','case_id':case,'review_status':'pending'},
                'clinical_validation':'not_validated',
                'provenance':{'method':'segmentation_surface_preview'},
                'fields':{'velocity':None,'pressure':None,'turbulence_intensity':None}}
        validation=validate_result(result)
        if not validation['valid']:
            raise ValueError(validation['errors'])
        write_json(BASE/'preview'/case/'result_placeholder.json',result)
        cases.append({'id':case,'label':label,'type':'patient_preview',
                      'mesh_url':f'../preview/{case}/viewer_mesh.json',
                      'result':result,'qc':data.get('qc',{}),
                      'note':'真实 CT 候选空气域。鼻孔与出口尚未审核，表面仅供查看。',
                      'localization_summary':summarize_localization(lm),
                      'coarse_localization':lm.get('coarse_localization'),
                      'coarse_adjustment':lm.get('coarse_adjustment'),
                      'landmarks':[{'id':k,**{field:v.get(field) for field in
                         ['label_zh','label_en','point_lps_mm','normal_lps','status']}}
                                   for k,v in lm['landmarks'].items() if v.get('point_lps_mm')]})
    patient_count=len(cases)
    cases.append(analytic_pipe())
    numeric=BASE/'reference'/'channel_numerical'/'viewer_mesh.json'
    if numeric.is_file():
        data=json.loads(numeric.read_text(encoding='utf-8'))
        if data.get('status')!='numerical_reference' or not validate_result(data.get('result'))['valid'] or data['result']['geometry'].get('kind')!='idealized':
            raise ValueError('Numerical reference metadata is invalid')
        cases.append({'id':'numerical_channel','label':'数值参考 · 平行板通道','type':'numerical_reference',
                      'mesh_url':'../reference/channel_numerical/viewer_mesh.json',
                      'note':'OpenFOAM 实际求解，细网格 12,800 单元；非患者二维通道。', 'landmarks':[]})
    if not patient_count:
        raise ValueError('No patient preview artifacts found; refusing an empty patient workspace')
    write_json(BASE/'viewer'/'workspace_data.json',{'schema':'nasal_workspace/v1',
        'patient_scan_count':patient_count,'patient_cfd_results':0,'cases':cases,
        'feedback_audit':feedback_audit,
        'note':'No patient flow fields have been computed or substituted with reference data.'})
    print(json.dumps({'patient_previews':patient_count,'analytic_references':1,'numerical_references':int(numeric.is_file()),
                      'patient_cfd_results':0,'page':str(BASE/'viewer'/'index.html')},ensure_ascii=False))


if __name__=='__main__':
    main()
