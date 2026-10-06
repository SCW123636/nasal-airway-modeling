"""Offline evidence packages and independent, version-bound medical feedback."""
from __future__ import annotations

import base64
import copy
from datetime import datetime
import hashlib
import io
import json
import math
from pathlib import Path
import re
import zipfile
from urllib.parse import unquote

from build_auto_landmark_review import read_case, script_json, sha256_json
from confirm_landmark_review import load_proposal_bundle
from ct_case_pipeline import (boundary_context, case_dir, current_artifacts, now,
                              read_json, sha256, verify_case_artifacts, write_json)

EXISTING_CASES = ('p0', 'p1', 'p2', 'p3', 'p3t1')
DECISIONS = {'pending', 'accept', 'reject', 'adjust', 'insufficient'}
EVIDENCE_LABELS = {'axial': '轴向 CT', 'coronal': '冠状 CT', 'sagittal': '矢状 CT',
                   'oral_overlay': '口腔排除叠加', 'sinus_overlay': '鼻窦排除叠加',
                   'openings_overlay': '入口与出口叠加'}


def triplet(value, normal=False):
    try:
        valid = (isinstance(value, list) and len(value) == 3
                 and all(type(x) in (int, float) and math.isfinite(x) and abs(x) < 1e6 for x in value))
        return valid and (not normal or math.hypot(*value) > 1e-8)
    except (ValueError, OverflowError):
        return False


def text_field(value, name, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(name + '为空或格式无效')
    return value.strip()


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
    except (AttributeError, TypeError, ValueError):
        raise ValueError('反馈时间必须包含时区') from None
    return value


def safe_asset(root, relative):
    if not isinstance(relative, str):
        raise ValueError('证据路径无效')
    target = (root / unquote(relative).replace('\\', '/')).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError('证据路径超出病例目录')
    return target


def image_asset(path, title):
    raw = path.read_bytes()
    if len(raw) > 20 * 1024**2 or not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('核验图像不是有效 PNG 或超过 20 MB')
    digest = hashlib.sha256(raw).hexdigest()
    return {'title': title, 'sha256': digest}, 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')


class MedicalReviewStore:
    def __init__(self, manager, review_root):
        self.manager = manager
        self.review_root = Path(review_root).resolve()

    def storage(self, case):
        if case in EXISTING_CASES:
            return self.manager.root / 'existing_reviews' / case / 'medical_review'
        directory = case_dir(self.manager.root, case)
        self.manager.get(case)
        return directory / 'medical_review'

    def catalog(self):
        existing = [{'case': c, 'label': c + ' · 已有扫描'} for c in EXISTING_CASES
                    if (self.review_root / c / 'landmarks.json').is_file()]
        uploaded = [{'case': c['id'], 'label': '上传 CT · ' + c['id'][-6:]} for c in self.manager.list()
                    if c.get('artifacts', {}).get('review')]
        return {'cases': existing + uploaded}

    def point_source(self, case):
        if case in EXISTING_CASES:
            root = self.review_root
            bundle = load_proposal_bundle(root / 'index.html')
            source = root / case / 'landmarks.json'
            report = read_json(source)
            ct = Path(report.get('source_ct', ''))
            inputs = report.get('input_provenance', {}).get('input_sha256', {})
            if not inputs or not ct.is_file():
                raise ValueError('现有扫描缺少可核验的 CT 来源')
            for relative, expected in inputs.items():
                target = safe_asset(ct.parent, relative)
                if not target.is_file() or sha256(target) != expected:
                    raise ValueError('CT 或分割已变化，不能导出旧候选')
            identity = {'case': case, 'revision': 'original',
                        'input_sha256': {k.replace('\\', '/'): v for k, v in inputs.items()}}
        else:
            data = self.manager.get(case)
            if data['status'] not in ('awaiting_review', 'review_recorded') or case in self.manager.pending:
                raise ValueError('请等待当前病例候选生成完成')
            public, _, receipt = verify_case_artifacts(case_dir(self.manager.root, case), data)
            root = public / 'review'
            bundle = load_proposal_bundle(root / 'index.html')
            source = root / case / 'landmarks.json'
            identity = {'case': case, 'revision': data.get('current_revision', 'original'),
                        'input_sha256': {k.replace('\\', '/'): v for k, v in receipt['identity']['input_sha256'].items()}}
        current = read_case(source, root)
        embedded = next((c for c in bundle['cases'] if c['case'] == case), None)
        if (not embedded or embedded['source_sha256'] != current['source_sha256']
                or [(l['id'], l['proposal_sha256']) for l in embedded['landmarks']]
                != [(l['id'], l['proposal_sha256']) for l in current['landmarks']]):
            raise ValueError('审核页与磁盘候选不一致，请重新生成候选')
        identity['source_sha256'] = current['source_sha256']
        return current, root, bundle, identity

    def build(self, case, stage):
        """Rebuild the package identity from current disk data, never from a reply."""
        if stage not in ('landmarks', 'boundary'):
            raise ValueError('复核阶段无效')
        current, root, bundle, identity = self.point_source(case)
        items, images = [], {}

        def evidence(path, title):
            meta, image = image_asset(path, title)
            images[meta['sha256']] = image
            return meta

        if stage == 'landmarks':
            # Historical diagnostic images are eligible only for this exact source and inputs.
            audit_root = self.review_root / 'feedback_review'
            audit = read_json(audit_root / 'audit.json') if (audit_root / 'audit.json').is_file() else {}
            audited = next((c for c in audit.get('cases', []) if c.get('case') == case), None)
            audit_current = audit.get('original_proposal_sha256', {}).get(case) == current['source_sha256']
            if audited and audit_current:
                ct_hashes = set(identity['input_sha256'].values())
                audit_current = set(audited.get('input_sha256', {}).values()) == ct_hashes
            for landmark in current['landmarks']:
                p = landmark['proposal']
                views = []
                if landmark.get('overlay_url'):
                    path = safe_asset(root, landmark['overlay_url'])
                    if path.is_file():
                        views.append(evidence(path, '候选点与标签叠加'))
                old = next((l for l in (audited or {}).get('landmarks', []) if l['id'] == landmark['id']), None)
                if (audit_current and old and old.get('point_lps_mm') == p.get('point_lps_mm')):
                    for key, title in [('raw_image', '原始 CT 三视图'), ('labels_image', '标签叠加三视图'),
                                       ('sweep_image', '沿原法向 −2 至 +2 mm 对照')]:
                        path = safe_asset(audit_root, old.get(key))
                        if path.is_file():
                            views.append(evidence(path, title))
                items.append({'id': landmark['id'], 'label': p.get('label_zh') or landmark['id'],
                              'kind': 'landmark', 'proposal_sha256': landmark['proposal_sha256'],
                              'point_lps_mm': p.get('point_lps_mm'), 'normal_lps': p.get('normal_lps'),
                              'original_status': p.get('status'),
                              'reviewable': bool(views) and triplet(p.get('point_lps_mm')) and p.get('status') != 'unavailable',
                              'question': '候选点的位置和法向是否符合该解剖位置？',
                              'reasons': p.get('review_reasons', []), 'evidence': views})
        else:
            views, controls = {}, {}
            if case not in EXISTING_CASES:
                data = self.manager.get(case)
                ref = data.get('boundary_preview') or {}
                if ref.get('status') == 'generated':
                    draft = ref['draft_id']
                    directory = case_dir(self.manager.root, case)
                    context = boundary_context(directory, data, draft)
                    _, private = current_artifacts(directory, data)
                    manifest_path = private / 'draft_previews' / draft / 'manifest.json'
                    if sha256(manifest_path) != ref.get('sha256'):
                        raise ValueError('当前边界草稿已变化')
                    manifest = read_json(manifest_path)
                    controls = manifest['controls']
                    identity['boundary'] = context | {'draft_id': draft}
                    for key, label in EVIDENCE_LABELS.items():
                        views[key] = evidence(safe_asset(manifest_path.parent, manifest['outputs'][key]['path']), label)
            checks = [
                ('nostril_L', '左鼻孔入口边界', '入口平面位置、方向与保留范围是否合适？', ['axial','coronal','sagittal','openings_overlay']),
                ('nostril_R', '右鼻孔入口边界', '入口平面位置、方向与保留范围是否合适？', ['axial','coronal','sagittal','openings_overlay']),
                ('nasopharynx_outlet', '鼻咽出口边界', '出口平面是否保留鼻咽并排除口腔？', ['axial','coronal','sagittal','openings_overlay']),
                ('oral_exclusion', '口腔排除', '主气道是否正确排除了口腔区域？', ['axial','coronal','sagittal','oral_overlay']),
                *[(name, label + '排除', '主版本是否正确排除了' + label + '，且未误删鼻腔？', ['axial','coronal','sagittal','sinus_overlay'])
                  for name, label in [('maxillary','上颌窦'),('frontal','额窦'),('ethmoid','筛窦'),('sphenoid','蝶窦')]],
                ('final_geometry', '最终表面与壁面', '最终表面范围、开口和壁面是否完整？', []),
            ]
            for key, label, question, keys in checks:
                item_views = [views[k] for k in keys if k in views]
                items.append({'id': key, 'label': label, 'kind': 'boundary', 'question': question,
                              'reviewable': bool(keys) and len(item_views) == len(keys), 'evidence': item_views,
                              'reasons': ['最终表面尚未生成，待后续几何阶段补充证据'] if key == 'final_geometry'
                              else ['尚无当前版本的完整边界预览，需生成草稿后重新导出'] if len(item_views) != len(keys) else [],
                              'controls': controls.get('openings', {}).get(key) if key in ('nostril_L','nostril_R','nasopharynx_outlet')
                              else controls.get('oral_exclusion') if key == 'oral_exclusion'
                              else {'policy': 'exclude_sinuses', 'regions': ['maxillary','frontal','ethmoid','sphenoid']}
                              if key != 'final_geometry' else None})
        manifest = {'schema': 'medical_review_package/v1', 'case': case, 'stage': stage,
                    'coordinate_system': 'LPS', 'unit': 'mm', 'identity': identity, 'items': items}
        return {'manifest': manifest, 'package_sha256': sha256_json(manifest), 'images': images,
                'exported_at': now()}, bundle, current

    def _prepare_export(self, case, stage, template):
        payload, _, _ = self.build(case, stage)
        html = template.replace('__PACKAGE_DATA__', script_json(payload)).encode('utf-8')
        return payload, html

    def _check_exports(self, prepared):
        for payload, _ in prepared:
            manifest = payload['manifest']
            after, _, _ = self.build(manifest['case'], manifest['stage'])
            if payload['package_sha256'] != after['package_sha256']:
                raise ValueError('导出期间复核材料发生变化，请重试')

    def _register_exports(self, prepared):
        for payload, _ in prepared:
            write_json(self.storage(payload['manifest']['case']) / 'packages' /
                       (payload['package_sha256'] + '.json'), payload['manifest'])

    def export(self, case, stage):
        with self.manager.lock:
            template = Path(__file__).with_name('medical_review_template.html').read_text(encoding='utf-8')
            payload, html = self._prepare_export(case, stage, template)
            self._check_exports([(payload, html)])
            self._register_exports([(payload, html)])
            return html, payload['package_sha256']

    def export_batch(self, cases, stages):
        with self.manager.lock:
            for values, name in ((cases, '病例'), (stages, '复核阶段')):
                if (not isinstance(values, list) or not values
                        or any(not isinstance(value, str) for value in values)
                        or len(values) != len(set(values))):
                    raise ValueError('请选择有效且不重复的' + name)
            available = {entry['case'] for entry in self.catalog()['cases']}
            if any(case not in available for case in cases):
                raise ValueError('所选病例不存在或尚未生成候选')
            if any(stage not in ('landmarks', 'boundary') for stage in stages):
                raise ValueError('复核阶段无效')
            template = Path(__file__).with_name('medical_review_template.html').read_text(encoding='utf-8')
            prepared, total = [], 0
            for case in cases:
                for stage in stages:
                    try:
                        item = self._prepare_export(case, stage, template)
                    except (ValueError, FileNotFoundError, KeyError) as exc:
                        raise ValueError(f'{case}：{exc}') from exc
                    total += len(item[1])
                    if total > 200 * 1024**2:
                        raise ValueError('所选复核材料超过 200 MB，请分批导出')
                    prepared.append(item)
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for payload, html in prepared:
                    manifest = payload['manifest']
                    label = '切片' if manifest['stage'] == 'landmarks' else '边界'
                    archive.writestr(f"{manifest['case']}_{label}_医学复核.html", html)
                archive.writestr('医学复核使用说明.txt',
                                 '先解压，再用浏览器逐份打开 HTML。图像已内嵌，可离线填写。\n'
                                 '填写复核人，逐项记录结论和意见，点击“导出反馈”保存 JSON。\n'
                                 '每个病例、每个阶段的反馈分别保存，将反馈文件交回项目负责人。\n'
                                 '项目负责人在工作台使用“导入医学复核反馈”，核对后单独保存审核。\n'
                                 '证据未齐项目无法判定通过或调整，需补充证据后重新复核。\n')
            self._check_exports(prepared)
            self._register_exports(prepared)
            return output.getvalue()

    def validate(self, reply, manifest, digest):
        if not isinstance(reply, dict) or reply.get('schema') != 'medical_review_feedback/v1':
            raise ValueError('请选择医学复核包导出的反馈 JSON')
        if (reply.get('case') != manifest['case'] or reply.get('stage') != manifest['stage']
                or reply.get('package_sha256') != digest or reply.get('coordinate_system') != 'LPS' or reply.get('unit') != 'mm'):
            raise ValueError('反馈病例、阶段或复核包版本不匹配')
        clean = {'schema': 'medical_review_feedback/v1', 'case': manifest['case'], 'stage': manifest['stage'],
                 'package_sha256': digest, 'coordinate_system': 'LPS', 'unit': 'mm',
                 'reviewer': text_field(reply.get('reviewer'), '复核人', 120, True),
                 'reviewed_at': timestamp(reply.get('reviewed_at')), 'items': []}
        incoming = reply.get('items')
        if not isinstance(incoming, list) or len(incoming) != len(manifest['items']):
            raise ValueError('反馈需包含核验包的全部条目，包括未审核项')
        expected = {i['id']: i for i in manifest['items']}
        seen = set()
        for record in incoming:
            if not isinstance(record, dict) or not isinstance(record.get('id'), str) or record['id'] not in expected or record['id'] in seen:
                raise ValueError('反馈含未知或重复条目')
            key = record['id']; seen.add(key)
            item = expected[key]
            decision = record.get('decision')
            if not isinstance(decision, str) or decision not in DECISIONS:
                raise ValueError('逐项反馈结论无效')
            if decision in ('accept', 'adjust') and not item['reviewable']:
                raise ValueError('证据未齐条目不能判定通过或调整')
            note = text_field(record.get('note', ''), '逐项意见', 5000, decision in ('reject', 'adjust'))
            point, normal = record.get('adjusted_point_lps_mm'), record.get('adjusted_normal_lps')
            if decision == 'adjust' and item['kind'] == 'landmark':
                if not triplet(point) or (normal is not None and not triplet(normal, True)):
                    raise ValueError('调整坐标或法向无效')
            elif point is not None or normal is not None:
                raise ValueError('非点位调整项不能携带调整坐标')
            clean['items'].append({'id': key, 'decision': decision, 'note': note,
                                   'adjusted_point_lps_mm': point, 'adjusted_normal_lps': normal})
        return clean

    def import_feedback(self, case, reply):
        with self.manager.lock:
            root = self.storage(case)
            digest = reply.get('package_sha256') if isinstance(reply, dict) else None
            if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                raise ValueError('复核包编号无效')
            path = root / 'packages' / (digest + '.json')
            if not path.is_file():
                raise ValueError('这份反馈不属于本机为此病例导出的复核包')
            manifest = read_json(path)
            if sha256_json(manifest) != digest:
                raise ValueError('本机复核包登记已损坏，请重新导出')
            current, _, _ = self.build(case, manifest['stage'])
            if current['package_sha256'] != digest:
                raise ValueError('反馈对应的候选或证据已过期，请导出当前版本重新复核')
            clean = self.validate(reply, manifest, digest)
            if self.build(case, manifest['stage'])[0]['package_sha256'] != digest:
                raise ValueError('导入期间复核材料发生变化，请重试')
            record_id = 'f_' + sha256_json(clean)[:24]
            target = root / 'feedback' / (record_id + '.json')
            if not target.exists():
                write_json(target, {'id': record_id, 'imported_at': now(), 'feedback': clean, 'manifest': manifest})
            return {'id': record_id, 'case': case, 'imported': True}

    def list_feedback(self, case):
        with self.manager.lock:
            records = []
            current_ids = {}
            for path in self.storage(case).glob('feedback/f_*.json'):
                record = read_json(path)
                stage = record['manifest']['stage']
                if stage not in current_ids:
                    try:
                        current_ids[stage] = self.build(case, stage)[0]['package_sha256']
                    except (FileNotFoundError, ValueError, KeyError):
                        current_ids[stage] = None
                record['current'] = current_ids[stage] == record['feedback']['package_sha256']
                records.append(record)
            return {'case': case, 'records': sorted(records, key=lambda r: r['imported_at'], reverse=True)}

    def decisions(self, case, record_id, selected):
        with self.manager.lock:
            if not isinstance(record_id, str) or not re.fullmatch(r'f_[0-9a-f]{24}', record_id):
                raise ValueError('反馈记录编号无效')
            record = read_json(self.storage(case) / 'feedback' / (record_id + '.json'))
            payload, bundle, source = self.build(case, 'landmarks')
            if record['feedback']['stage'] != 'landmarks' or payload['package_sha256'] != record['feedback']['package_sha256']:
                raise ValueError('该反馈已过期或不是点位意见')
            if sha256_json(record['manifest']) != payload['package_sha256']:
                raise ValueError('反馈证据登记已损坏')
            self.validate(record['feedback'], record['manifest'], payload['package_sha256'])
            available = {i['id']: i for i in record['feedback']['items'] if i['decision'] in ('accept','reject','adjust')}
            if (not isinstance(selected, list) or not selected or any(not isinstance(key, str) for key in selected)
                    or len(selected) != len(set(selected))
                    or any(key not in available for key in selected)):
                raise ValueError('请选择有明确结论的点位意见')
            converted = []
            for item in source['landmarks']:
                if item['id'] not in selected:
                    continue
                feedback = available[item['id']]
                p = item['proposal']
                converted.append({'landmark_id': item['id'], 'label_zh': p.get('label_zh'),
                                  'proposal_sha256': item['proposal_sha256'], 'original_status': p.get('status'),
                                  'original_point_lps_mm': p.get('point_lps_mm'), 'original_normal_lps': p.get('normal_lps'),
                                  **{k: copy.deepcopy(feedback[k]) for k in ('decision','note','adjusted_point_lps_mm','adjusted_normal_lps')},
                                  'updated_at': record['feedback']['reviewed_at']})
            return {'schema_version': '1.0', 'artifact_type': 'landmark_review_decisions',
                    'coordinate_system': 'LPS', 'unit': 'mm', 'reviewer': record['feedback']['reviewer'],
                    'exported_at': now(), 'proposal_bundle_sha256': bundle['proposal_bundle_sha256'],
                    'cases': [{'case': case, 'source_file': source['source_file'],
                               'source_sha256': source['source_sha256'], 'decisions': converted}]}
