"""Content-bound patient engineering admission; clinical status remains separate.

Inputs are provisioned on disk by trusted project tooling. HTTP callers supply
only a catalog case ID, never a filesystem path or an override flag.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
INPUT_ROOT = Path('C:/ts_work/project_cases/patient_cfd_inputs')
# Keep uploaded IDs identical to the pipeline definition, which uses 16 hex.
from ct_case_pipeline import CASE_RE as UPLOADED_CASE_RE
CASE_RE = re.compile(r'(?:p[0-9]+(?:t[0-9]+)?|' + UPLOADED_CASE_RE.pattern + r'|b[0-9]+_engineering)')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mesh_fingerprint(case):
    folder = Path(case) / 'constant/polyMesh'
    required = ('points','faces','owner','neighbour','boundary')
    if any(not (folder / name).is_file() for name in required):
        raise ValueError('完整 polyMesh 五个核心文件缺失')
    return {p.relative_to(folder).as_posix(): sha256(p) for p in sorted(folder.rglob('*')) if p.is_file()}


def contained(base, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError('准入记录只接受受控目录内的相对路径')
    target = (Path(base) / value).resolve()
    if not target.is_relative_to(Path(base).resolve()):
        raise ValueError('准入记录路径越界')
    return target


def admission(case_id, root=None, current_source_binding=None):
    if not isinstance(case_id, str) or not CASE_RE.fullmatch(case_id):
        raise ValueError('患者工程病例编号无效')
    folder = Path(root or INPUT_ROOT) / case_id
    checks = []
    def check(name, passed, detail, source='受控患者工程输入与内容指纹'):
        checks.append({'name': name, 'passed': bool(passed), 'detail': detail, 'source': source})
    path = folder / 'admission.json'
    if not path.is_file():
        check('final_surface_binding', False, '尚无与本例当前输入绑定的最终 CFD 表面及工程准入记录')
        check('volume_mesh_binding', False, '尚无与最终表面绑定的体网格与 checkMesh 原始证据')
        return {'passed': False, 'case_id': case_id, 'checks': checks,
                'blocking_reasons': [c['detail'] for c in checks], 'clinical_validation': 'not_validated'}
    data = json.loads(path.read_text(encoding='utf-8'))
    check('admission_identity', data.get('schema') == 'nasal_patient_engineering_admission/v1' and data.get('case_id') == case_id,
          '准入记录 schema 与病例身份匹配')
    resolved = {}
    try:
        from cfd_contract import validate_config
        surface = contained(folder, data['surface']['file'])
        template = contained(folder, data['template_dir'])
        config_path = contained(folder, data['config_file'])
        config = json.loads(config_path.read_text(encoding='utf-8'))
        manifest = json.loads((template / 'case_manifest.json').read_text(encoding='utf-8'))
        binding = data.get('current_source_binding')
        if case_id.endswith('_engineering'):
            originals = data.get('frozen_sources', {})
            frozen = bool(originals) and binding == {'kind':'frozen_standalone_sample','sample_id':case_id}
            for name, item in originals.items():
                source_path = contained(folder,item['file'])
                frozen = frozen and source_path.is_file() and sha256(source_path) == item.get('sha256')
            check('current_source_binding', frozen, '独立冻结b15工程样例绑定源VTP/export/msh，不继承用户病例身份')
        else:
            check('current_source_binding', bool(current_source_binding) and binding == current_source_binding,
                  '当前CT、landmark、分割/边界revision身份必须与该工程输入一致；改变后重新准入')
        check('final_surface_binding', surface.is_file() and sha256(surface) == data['surface']['sha256'], '最终 CFD 表面内容哈希匹配')
        check('mesh_content_binding', mesh_fingerprint(template) == data['mesh_fingerprint'], '体网格所有文件内容指纹匹配')
        check('config_content_binding', sha256(config_path) == data['config_sha256'], '物性、边界、数值配置指纹匹配')
        check('surface_mesh_provenance', manifest.get('patient_case_id') == case_id and manifest.get('final_surface_sha256') == data['surface']['sha256']
              and manifest.get('source_mesh_sha256') == data.get('source_mesh_sha256'), 'case manifest 绑定该病例、最终表面和生成网格来源')
        report = validate_config(config)
        check('configuration_contract', report['valid'], '；'.join(report['errors']) or '配置语义有效；专业审核 readiness 独立保留')
        check('patient_config_identity', config.get('geometry', {}).get('kind') == 'patient' and config['geometry'].get('case_id') == case_id
              and config['geometry'].get('sha256') == data['surface']['sha256'], '配置绑定同一患者表面，不继承其他患者身份')
        authorization = data.get('engineering_authorization', {})
        evidence = contained(folder, authorization.get('record_file'))
        check('engineering_authorization', authorization.get('scope') == 'isolated_engineering_trial_not_clinical'
              and authorization.get('case_id') == case_id and authorization.get('surface_sha256') == data['surface']['sha256']
              and authorization.get('config_sha256') == data['config_sha256'] and evidence.is_file()
              and sha256(evidence) == authorization.get('record_sha256'), '病例限定的工程试算许可与证据哈希；不授予临床有效性')
        mesh_log = contained(folder, data['check_mesh_log'])
        check('mesh_diagnostics_present', mesh_log.is_file() and 'Mesh stats' in mesh_log.read_text(errors='replace'), '保留原 checkMesh；失败项作为工程风险记录')
        resolved = {'folder': str(folder.resolve()), 'template': str(template), 'config_path': str(config_path),
                    'admission_path': str(path.resolve()), 'admission_sha256': sha256(path),
                    'clinical_readiness_reasons': report['warnings']}
    except (KeyError, ValueError, OSError, TypeError) as exc:
        check('input_evidence_complete', False, '输入证据不完整或失配：' + str(exc))
    return {'passed': all(c['passed'] for c in checks), 'case_id': case_id, 'checks': checks,
            'blocking_reasons': [c['name'] + '：' + c['detail'] for c in checks if not c['passed']],
            'clinical_validation': 'not_validated', **resolved}


def registered_cases(root=None):
    root = Path(root or INPUT_ROOT)
    return [p.name for p in sorted(root.iterdir()) if p.is_dir() and CASE_RE.fullmatch(p.name) and (p / 'admission.json').is_file()] if root.is_dir() else []


def validate_engineering_authorization(case, config_path, path):
    """Validate a narrowly bound, auditable allowance, never clinical readiness."""
    case, config_path, path = Path(case).resolve(), Path(config_path).resolve(), Path(path).resolve()
    if not path.is_relative_to(case) or not config_path.is_relative_to(case):
        raise ValueError('授权和配置必须在该隔离case内')
    data = json.loads(path.read_text(encoding='utf-8'))
    config = json.loads(config_path.read_text(encoding='utf-8'))
    manifest = json.loads((case / 'case_manifest.json').read_text(encoding='utf-8'))
    from cfd_contract import validate_config
    report = validate_config(config)
    if not report['valid']:
        raise ValueError('工程授权不能覆盖配置错误：' + '；'.join(report['errors']))
    if data.get('schema') != 'nasal_bound_engineering_authorization/v1' or data.get('scope') != 'isolated_engineering_trial_not_clinical':
        raise ValueError('工程授权 schema/scope 无效')
    identity = data.get('case_id')
    if not isinstance(identity, str) or not CASE_RE.fullmatch(identity) or manifest.get('patient_case_id') != identity or config.get('geometry', {}).get('case_id') != identity:
        raise ValueError('工程授权病例身份不匹配')
    surface = contained(case, data.get('surface_file'))
    if not surface.is_file() or sha256(surface) != data.get('surface_sha256') or manifest.get('final_surface_sha256') != data.get('surface_sha256'):
        raise ValueError('工程授权最终表面失配')
    if config.get('geometry', {}).get('sha256') != data.get('surface_sha256') or sha256(config_path) != data.get('config_sha256'):
        raise ValueError('工程授权配置失配')
    if mesh_fingerprint(case) != data.get('mesh_fingerprint') or manifest.get('source_mesh_sha256') != data.get('source_mesh_sha256'):
        raise ValueError('工程授权网格失配')
    source = contained(case, data.get('record_file'))
    if not source.is_file() or sha256(source) != data.get('record_sha256'):
        raise ValueError('工程裁定来源证据失配')
    if not isinstance(data.get('source_record'), str) or not data['source_record'].strip():
        raise ValueError('工程裁定可定位来源缺失')
    return {'allowed': True, 'case_id': identity, 'scope': data['scope'],
            'authorization_sha256': sha256(path), 'source_record': data['source_record'],
            'clinical_validation': 'not_validated', 'readiness_warnings': report['warnings'],
            'mesh_fingerprint': data['mesh_fingerprint'], 'config_sha256': data['config_sha256'],
            'surface_sha256': data['surface_sha256']}
