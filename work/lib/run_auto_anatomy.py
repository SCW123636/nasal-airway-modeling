"""Reproducible local batch runner for anatomical proposals and review artifacts.

No model training, clinical approval, segmentation edits or CFD execution.
Unchanged inputs and verified output hashes can reuse the last successful run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
LIB = Path(__file__).resolve().parent
CASES = ['p0', 'p1', 'p2', 'p3', 'p3t1']
LABELS = ['nasal_cavity_left', 'nasal_cavity_right', 'nasopharynx',
          'oropharynx', 'hard_palate', 'soft_palate']
from coarse_anatomy_prior import DEFAULT_LIBRARY, patient_id


def file_sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def input_identity(data, reference_library=None, reference_patient_id=None):
    import SimpleITK
    import scipy
    import numpy
    paths = [data/'ct.nii.gz'] + [data/'masks'/f'{n}.nii.gz' for n in LABELS]
    return {'input_sha256': {str(p.relative_to(data)): file_sha256(p) for p in paths},
            'code_sha256': {n: file_sha256(LIB/n) for n in
                            ['auto_anatomy_landmarks.py', 'coarse_anatomy_prior.py', 'ts_quality_gate.py']},
            'coarse_reference': {
                'library_sha256': file_sha256(reference_library or DEFAULT_LIBRARY)
                    if Path(reference_library or DEFAULT_LIBRARY).is_file() else None,
                'patient_id': reference_patient_id or patient_id(data.name)},
            'software': {'python': sys.version, 'SimpleITK': SimpleITK.Version_VersionString(),
                         'scipy': scipy.__version__, 'numpy': numpy.__version__}}


def output_files(out, qc, case):
    paths = [out/'landmarks.json', out/'landmarks.mrk.json',
             out/'review_config_proposed.json', out/'review.png', out/'coarse_localization.json',
             out/'coarse_adjustment.json',
             qc/f'gate_{case}.json', qc/f'gate_{case}.png']
    report = json.loads((out/'landmarks.json').read_text(encoding='utf-8'))
    paths.extend(out/p['overlay_png'] for p in report['landmarks'].values()
                 if p['point_lps_mm'] is not None)
    return list(dict.fromkeys(paths))


def can_reuse(receipt, identity):
    if receipt.get('identity') != identity or receipt.get('status') != 'generated':
        return False
    hashes = receipt.get('output_sha256', {})
    return bool(hashes) and all(Path(p).is_file() and file_sha256(p) == h
                                for p, h in hashes.items())


def run_stage(command, log):
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    with Path(log).open('w', encoding='utf-8') as output:
        result = subprocess.run([sys.executable, *map(str, command)],
                                stdout=output, stderr=subprocess.STDOUT, env=env)
    if result.returncode:
        raise RuntimeError(f'Stage exited {result.returncode}; see {log}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', nargs='+', choices=CASES, default=CASES)
    parser.add_argument('--data-base', type=Path, default=Path('C:/ts_work'))
    parser.add_argument('--out-base', type=Path, default=ROOT/'work'/'06_auto_landmarks')
    parser.add_argument('--qc-base', type=Path, default=ROOT/'work'/'05_ts_seg')
    parser.add_argument('--force', action='store_true', help='Recompute even if content hashes match')
    parser.add_argument('--reference-library', type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument('--patient-id', help='Anonymous patient group for a single case')
    args = parser.parse_args()
    if args.patient_id and len(args.cases) != 1:
        parser.error('--patient-id requires exactly one case')
    args.out_base.mkdir(parents=True, exist_ok=True)
    logdir = args.out_base/'logs'; logdir.mkdir(exist_ok=True)
    manifest_path = args.out_base/'pipeline_manifest.json'
    previous = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.is_file() else {}
    results = {}
    started = time.time()
    for case in args.cases:
        try:
            identity = input_identity(args.data_base/case,args.reference_library,args.patient_id)
            prior = previous.get('cases', {}).get(case, {})
            if not args.force and can_reuse(prior, identity):
                results[case] = dict(prior, execution='reused_verified_unchanged_content')
                print(case + ': unchanged inputs and outputs verified; reused', flush=True)
                continue
            print(case + ': checking segmentation and proposing landmarks', flush=True)
            run_stage([LIB/'ts_quality_gate.py', case, '--data-dir', args.data_base/case,
                       '--out-dir', args.qc_base/case], logdir/f'{case}_quality.log')
            command = [LIB/'auto_anatomy_landmarks.py', case, '--data-base', args.data_base,
                       '--out-base', args.out_base, '--reference-library', args.reference_library]
            if args.patient_id:
                command += ['--patient-id', args.patient_id]
            run_stage(command, logdir/f'{case}_landmarks.log')
            gate = json.loads((args.qc_base/case/f'gate_{case}.json').read_text(encoding='utf-8'))
            if gate.get('data_integrity_status') != 'pass':
                raise ValueError('Data integrity did not pass')
            results[case] = {'identity': identity, 'status': 'generated', 'execution': 'computed',
                             'medical_or_cfd_validation_pass': False,
                             'output_sha256': {str(p.resolve()): file_sha256(p)
                                               for p in output_files(args.out_base/case,args.qc_base/case,case)}}
        except Exception as error:
            results[case] = {'status': 'failed', 'error': str(error),
                             'medical_or_cfd_validation_pass': False}
            print(case + ': FAILED: ' + str(error), file=sys.stderr, flush=True)
    successful = [c for c in args.cases if results[c]['status'] == 'generated']
    batch_summary = []
    for case in args.cases:
        if case not in successful:
            batch_summary.append({'case': case, **results[case]})
            continue
        report_path = args.out_base/case/'landmarks.json'
        report = json.loads(report_path.read_text(encoding='utf-8'))
        # Bind browser review identity to original CT/label contents as well as proposals.
        if report.get('input_provenance') != results[case]['identity']:
            report['input_provenance'] = results[case]['identity']
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            results[case]['output_sha256'][str(report_path.resolve())] = file_sha256(report_path)
        batch_summary.append({'case': case, 'landmarks': {
            key: {field: lm.get(field) for field in ('status','point_lps_mm','review_reasons')}
            for key,lm in report['landmarks'].items()}, 'out': str(report_path.parent)})
    (args.out_base/'batch_summary.json').write_text(
        json.dumps(batch_summary, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest = {'schema': 'auto_anatomy_pipeline/v1', 'cases': results,
                'elapsed_seconds': round(time.time()-started, 2),
                'medical_or_cfd_validation_pass': False,
                'note': 'Content hashes permit computation reuse, never medical acceptance.'}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    if successful:
        # Limit displayed cases to current successful outputs. Failed old outputs stay off the page.
        run_stage([LIB/'build_auto_landmark_review.py', '--base-dir', args.out_base,
                   '--cases', *successful], logdir/'review_page.log')
        run_stage([LIB/'summarize_auto_anatomy.py', '--base-dir', args.out_base,
                   '--qc-base', args.qc_base, '--cases', *successful], logdir/'summary.log')
    else:
        (args.out_base/'index.html').write_text(
            '<!doctype html><meta charset="utf-8"><title>本批自动定位未完成</title>'
            '<h1>本批没有成功完成的病例</h1><p>请查看 pipeline_manifest.json 与 logs。'
            '本页面不展示以前的候选，防止把旧结果当作本批输出。</p>', encoding='utf-8')
        (args.out_base/'auto_anatomy_summary.json').write_text(
            json.dumps({'assembly_status':'failed','cases':results},ensure_ascii=False,indent=2), encoding='utf-8')
        (args.out_base/'自动定位回测报告.md').write_text(
            '# 本批自动定位未完成\n\n没有成功病例，请查看 pipeline_manifest.json 与 logs。\n', encoding='utf-8')
    print(json.dumps({'completed': successful,
                      'failed': [c for c in args.cases if c not in successful],
                      'review_page': str(args.out_base/'index.html'),
                      'manifest': str(manifest_path)}, ensure_ascii=False, indent=2))
    return int(len(successful) != len(args.cases))


if __name__ == '__main__':
    raise SystemExit(main())
