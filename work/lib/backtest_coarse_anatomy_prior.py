"""Exploratory leave-one-patient-out comparison against EXISTING CANDIDATES.

No clinical ground truth is available. This never writes to the reviewed
reference library. Different scans of one patient are excluded together.
"""
from __future__ import annotations

import argparse
from itertools import product
from pathlib import Path

import numpy as np

from coarse_anatomy_prior import (LANDMARKS, ROOT, load_descriptor, patient_id,
                                 predict, read_json, sha256, write_json)


def summarize(values):
    return {'count': len(values), 'median_mm': float(np.median(values)),
            'p95_mm': float(np.percentile(values, 95)), 'max_mm': float(max(values))} if values else {'count': 0}


def box_transfer(point, source, target):
    low_s, high_s = (np.asarray(source[k]) for k in ('min', 'max'))
    low_t, high_t = (np.asarray(target[k]) for k in ('min', 'max'))
    return low_t + (np.asarray(point) - low_s) / (high_s - low_s) * (high_t - low_t)


def scan_box(image):
    points = np.array([image.TransformIndexToPhysicalPoint(tuple(q))
                       for q in product(*[(0, int(v) - 1) for v in image.GetSize()])])
    return {'min': points.min(0).tolist(), 'max': points.max(0).tolist()}


def run(data_base, proposal_base, output, cases):
    output.mkdir(parents=True, exist_ok=True)
    refs, reports, images, boxes = [], {}, {}, {}
    for case in cases:
        print(case + ': measuring anatomical bounds', flush=True)
        desc, image = load_descriptor(data_base / case)
        report = read_json(proposal_base / case / 'landmarks.json')
        if report['case'] != case or report['coordinate_system'] != 'LPS' or report['unit'] != 'mm':
            raise ValueError('Candidate report identity/units mismatch')
        # These are comparison candidates, explicitly not human-approved standards.
        refs.append({'case': case, 'patient_id': patient_id(case), 'descriptor': desc,
                     'landmarks': {key: lm for key, lm in report['landmarks'].items() if lm.get('point_lps_mm') is not None},
                     'provenance': {'ct_sha256': sha256(data_base / case / 'ct.nii.gz'),
                                    'proposal_sha256': sha256(proposal_base / case / 'landmarks.json')},
                     'reference_status': 'exploratory_unconfirmed_candidate'})
        reports[case], images[case], boxes[case] = report, image, scan_box(image)
    rows, priors = [], {}
    by_case = {ref['case']: ref for ref in refs}
    for target in refs:
        case = target['case']
        rough = predict(target['descriptor'], refs, case, target['patient_id'], target['provenance']['ct_sha256'], images[case])
        rough['usage'] = 'exploratory comparison only; unconfirmed candidates excluded from production library'
        priors[case] = rough
        write_json(output / (case + '_exploratory_prior.json'), rough)
        accepted = [by_case[entry['case']] for entry in rough['accepted_references']]
        for key in LANDMARKS:
            pred = rough['landmarks'].get(key)
            actual = reports[case]['landmarks'].get(key, {}).get('point_lps_mm')
            if pred is None or actual is None:
                continue
            errors = {'anatomy_frame': float(np.linalg.norm(np.asarray(pred['point_lps_mm']) - actual))}
            for method in ('scan_box', 'nasal_lps_box'):
                groups = {}
                for source in accepted:
                    if key not in source['landmarks']:
                        continue
                    source_box = boxes[source['case']] if method == 'scan_box' else source['descriptor']['exact_extrema_lps_mm']
                    target_box = boxes[case] if method == 'scan_box' else target['descriptor']['exact_extrema_lps_mm']
                    point = box_transfer(source['landmarks'][key]['point_lps_mm'], source_box, target_box)
                    groups.setdefault(source['patient_id'], []).append(point)
                if groups:
                    point = np.median([np.median(v, axis=0) for v in groups.values()], axis=0)
                    errors[method] = float(np.linalg.norm(point - actual))
            from coarse_anatomy_prior import in_search_box
            rows.append({'case': case, 'landmark': key, 'independent_reference_patients': pred['independent_patients'],
                         'prior_status': pred['status'], 'distance_to_existing_candidate_mm': errors,
                         'candidate_within_search_box': bool(in_search_box(actual, pred, target['descriptor']['frame']))})
    summary = {method: summarize([r['distance_to_existing_candidate_mm'][method] for r in rows
                                 if method in r['distance_to_existing_candidate_mm']])
               for method in ('scan_box', 'nasal_lps_box', 'anatomy_frame')}
    result = {'schema': 'coarse_prior_exploratory_backtest/v1', 'cases': cases,
              'independent_patients': len({patient_id(c) for c in cases}),
              'clinical_ground_truth': False, 'production_library_modified': False,
              'comparison': 'distance to existing automatic proposals, not anatomical localization error',
              'summary': summary, 'rows': rows,
              'excluded_or_unavailable_points': sum(len(LANDMARKS) - len(priors[c]['landmarks']) for c in cases)}
    write_json(output / 'backtest.json', result)
    from coarse_anatomy_prior import PARAMETERS
    lines = ['# 三轴比例粗定位：探索性回测', '', '日期：2026-10-03。', '',
             f'{len(cases)} 组扫描、{result["independent_patients"]} 位患者。逐患者排除本人及其其他时点；p3 和 p3t1 不互作参考。', '',
             '**比较对象是现有自动候选，不是人工真值。以下距离不能称为医学定位误差或准确率。**', '',
             '| 方法 | 可比较点数 | 距离中位数 mm | P95 mm | 最大 mm |', '|---|---:|---:|---:|---:|']
    names = {'scan_box': '整份 CT 包围盒比例', 'nasal_lps_box': '鼻腔结构 LPS 极值比例',
             'anatomy_frame': '校正姿态＋鼻腔结构稳健范围比例'}
    for method, values in summary.items():
        if values['count']:
            lines.append(f'| {names[method]} | {values["count"]} | {values["median_mm"]:.2f} | {values["p95_mm"]:.2f} | {values["max_mm"]:.2f} |')
    covered = sum(r['candidate_within_search_box'] for r in rows)
    lines += ['', f'搜索框覆盖现有候选：{covered}/{len(rows)}。',
              f'未生成预设：{result["excluded_or_unavailable_points"]} 点；原因和逐参考缩放比见各例 exploratory_prior.json。', '',
              '使用相同的适用参考病例比较三种方法，参考按患者等权。距离汇总包含同一人的两个时点，并非 16 个独立患者样本。局部框宽度使用工程余量＋参考间差异；没有按本次候选反调参数。', '',
              '有效比较来自 p0、p1、p3、p3t1 的左右鼻孔及左右后鼻孔，涉及三位患者。p2 因硬腭拟合 RMS 1.832 mm 超过初始工程限值没有启用粗定位；其余四例的出口缺少完整独立参考。', '',
              '## 工程边界', '',
              '- 当前正式 reference_library.json 没有人工确认标准，探索数据没有进入正式库。',
              '- 只映射点位和搜索区域。目标 CT、原始毫米尺寸、气道几何不缩放。',
              '- 鼻腔、硬腭或鼻咽标签触边时停用粗定位；软腭/口咽触边时不提供出口预设。',
              '- 搜索点需要至少两位独立患者；一位只能显示预计位置。参考分歧过大时不限制搜索。',
              '- 空气射线和语义界面仍负责本例候选；未找到本例证据时不填入模板点。', '',
              '## 下一次有效验证', '',
              '先登记独立人工确认点，再逐患者留出验证，报告点位距离、搜索框漏检、最终候选变化和人工调整量。不同扫描覆盖、姿态、鼻中隔偏曲及术后结构需分别观察。', '',
              '工程参数：`' + str(PARAMETERS) + '`。']
    (output / '探索性回测报告.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(summary, flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-base', type=Path, default=Path('C:/ts_work'))
    parser.add_argument('--proposal-base', type=Path, default=ROOT / 'work' / '06_auto_landmarks')
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'work' / '09_coarse_localization')
    parser.add_argument('--cases', nargs='+', default=['p0', 'p1', 'p2', 'p3', 'p3t1'])
    args = parser.parse_args()
    run(args.data_base, args.proposal_base, args.out_dir, args.cases)


if __name__ == '__main__':
    main()
