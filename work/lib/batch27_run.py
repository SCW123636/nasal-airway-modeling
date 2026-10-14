"""Batch driver: 27 new cases -> segmentation -> surface -> proposals -> v2 report.

The normal path only. Special cases (unreadable series, empty masks, degenerate
geometry) are recorded and stepped over; they are not what this run is for.

Each stage is an existing script, invoked as a subprocess so a crash in one stage
cannot take the batch with it:

  1 ts_nasal_seg.py--batch-dir ...        DICOM -> NIfTI -> TotalSegmentator masks
  2 auto_anatomy_landmarks.py <case>       masks -> landmarks.json proposals
  3 batch27_surface.py                     mask union + HU cut -> source_surface.vtp
  4 auto_opening_pipeline.py --proposals   -> v2 placement report

All four stages run as subprocesses, so a crash in one stage cannot take the
batch with it. Every stage is re-runnable on its own and skips work already on
disk, which matters because stage 1 costs ~136 s per case on CPU.

Naming: cases are b01..b27 so they cannot collide with the p0/p1/p2/p3/p3t1
reviewed pilot cases, which keep their own meaning.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('D:/项目/鼻腔建模')
LIB = ROOT / 'work' / 'lib'
CHOICE = ROOT / 'work' / '10_nasalseg_intake' / 'batch27_series_choice.json'
TS_BASE = Path('C:/ts_work')
SURFACE_ROOT = TS_BASE / 'batch27_surfaces'
OPENING_ROOT = TS_BASE / 'batch27_opening'
NASAL_PY = Path('C:/Users/lenovo/AppData/Local/Programs/Python/Python310/python.exe')
ROI_LABELS = ('nasal_cavity_left', 'nasal_cavity_right', 'nasopharynx')


def run(cmd, timeout):
    t0 = time.time()
    try:
        p = subprocess.run([str(c) for c in cmd], capture_output=True,
                           timeout=timeout, text=True, encoding='utf-8', errors='replace')
        return {'returncode': p.returncode, 'elapsed_s': round(time.time() - t0, 1),
                'stdout_tail': p.stdout[-1200:] if p.stdout else '',
                'stderr_tail': p.stderr[-800:] if p.stderr else ''}
    except subprocess.TimeoutExpired:
        return {'returncode': None, 'elapsed_s': round(time.time() - t0, 1),
                'why': 'timeout'}
    except Exception as exc:
        return {'returncode': None, 'elapsed_s': round(time.time() - t0, 1),
                'why': f'{type(exc).__name__}: {exc}'}


def check_masks(case_dir):
    """Independent check on the stage-1 output, not just its exit code."""
    d = TS_BASE / case_dir / 'masks'
    if not d.is_dir():
        return {'ok': False, 'why': 'mask_dir missing'}
    have = {p.name.replace('.nii.gz', '') for p in d.glob('*.nii.gz')}
    missing = [r for r in ROI_LABELS if r not in have]
    sizes = {}
    import SimpleITK as sitk
    nonempty = {}
    for r in ROI_LABELS:
        f = d / f'{r}.nii.gz'
        if f.is_file():
            a = sitk.GetArrayFromImage(sitk.ReadImage(str(f)))
            sizes[r] = list(a.shape)
            nonempty[r] = int((a > 0).sum())
    bad = [r for r in ROI_LABELS if nonempty.get(r, 0) == 0]
    return {'ok': not missing and not bad, 'missing_labels': missing,
            'empty_labels': bad, 'voxels': nonempty, 'shape_zyx': sizes}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cases', nargs='+', default=None, help='e.g. b01 b02')
    ap.add_argument('--device', default='cpu')
    ap.add_argument('--seg-timeout', type=int, default=7200)
    ap.add_argument('--skip-seg', action='store_true')
    ap.add_argument('--output', type=Path,
                    default=ROOT / 'work' / '10_nasalseg_intake' / 'batch_run.json')
    args = ap.parse_args()

    cases = args.cases or [f'b{i:02d}' for i in range(1, 28)]
    report = {'schema': 'batch27_run/v2',
              'stages': ['seg', 'proposal', 'surface', 'placement'],
              'surface_src': str(SURFACE_ROOT), 'opening_out': str(OPENING_ROOT),
              'cases': {}}

    for case in cases:
        entry = {'case': case}
        if not args.skip_seg:
            r = run([NASAL_PY, '-u', LIB / 'ts_nasal_seg.py', '--batch-dir',
                     CHOICE.parent, '--device', args.device, case],
                    args.seg_timeout)
            entry['segmentation'] = {k: v for k, v in r.items() if k != 'stdout_tail'}
            entry['segmentation']['stdout_tail'] = r.get('stdout_tail', '')[-500:]
        entry['mask_check'] = check_masks(case)
        if entry['mask_check']['ok']:
            p = run([NASAL_PY, '-u', LIB / 'auto_anatomy_landmarks.py', case,
                     '--data-base', TS_BASE], 1800)
            entry['proposal'] = {k: v for k, v in p.items() if k != 'stdout_tail'}
            entry['proposal']['stdout_tail'] = p.get('stdout_tail', '')[-300:]
            aj = ROOT / 'work' / '06_auto_landmarks' / case / 'landmarks.json'
            entry['proposal_json'] = str(aj) if aj.is_file() else None
            entry['proposal_ok'] = bool(entry['proposal_json'])

            s = run([NASAL_PY, '-u', LIB / 'batch27_surface.py', '--cases', case,
                     '--out', SURFACE_ROOT], 3600)
            entry['surface'] = {k: v for k, v in s.items() if k != 'stdout_tail'}
            surf = SURFACE_ROOT / case / 'source_surface.vtp'
            entry['surface_ok'] = surf.is_file()

            if entry.get('proposal_ok') and entry['surface_ok']:
                o = run([NASAL_PY, '-u', LIB / 'auto_opening_pipeline.py',
                         '--output', OPENING_ROOT, '--proposals',
                         ROOT / 'work' / '06_auto_landmarks', '--src',
                         SURFACE_ROOT, '--cases', case], 5400)
                entry['placement'] = {k: v for k, v in o.items() if k != 'stdout_tail'}
                oj = OPENING_ROOT / f'{case}.json'
                if oj.is_file():
                    rep = json.loads(oj.read_text(encoding='utf-8'))
                    entry['placement_decision'] = rep.get('decision')
                    entry['placement_areas_mm2'] = rep.get('patch_areas_mm2')
                    entry['placement_escalations'] = rep.get('escalations')
        report['cases'][case] = entry
        mc = entry['mask_check']
        print(f"{case}: masks {'OK' if mc['ok'] else 'BAD'}"
              f" proposal={'OK' if entry.get('proposal_ok') else '-'}"
              f" surface={'OK' if entry.get('surface_ok') else '-'}"
              f" opening={entry.get('placement_decision', '-')}"
              f" voxels={list(mc.get('voxels', {}).values())}", flush=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    ok = sum(1 for c in report['cases'].values() if c['mask_check']['ok'])
    opened = sum(1 for c in report['cases'].values()
                 if c.get('placement_decision') == 'auto_pass')
    print(f'\nmask check {ok}/{len(report["cases"])}; auto_pass {opened}; '
          f'written {args.output}')


if __name__ == '__main__':
    main()