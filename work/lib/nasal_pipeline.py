"""Single entry point for the normal path: DICOM -> v2 opening report.

Everything here is defined in work/07_cfd_pipeline/正常路径基本方法_v1.md.
This file exists because the method had been spread across five scripts that
each had to be called by hand, which is not a method, it is a pile of steps.

Five stages, run as subprocesses so one crash cannot take the batch down, and so
each stage can be re-run on its own. Stages skip work already on disk, which
matters because stage 2 costs ~136 s per case on CPU.

    1 series      batch27_series_choice.py     -> one DICOM dir per case
    2 segment     ts_nasal_seg.py --batch-dir  -> ct.nii.gz + masks
    3 propose     auto_anatomy_landmarks.py    -> landmarks.json
    4 surface     batch27_surface.py           -> source_surface.vtp
    5 place       auto_opening_pipeline.py     -> per-case report

Normal cases only. A case that fails any of N1-N6 is reported as escalated with
the gate that caught it, and is not retried or worked around here.
"""
import argparse
import hashlib
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path('D:/项目/鼻腔建模')
LIB = ROOT / 'work' / 'lib'
TS_BASE = Path('C:/ts_work')
SURFACE_ROOT = TS_BASE / 'batch27_surfaces'
OPENING_ROOT = TS_BASE / 'batch27_opening'
PY = Path('C:/Users/lenovo/AppData/Local/Programs/Python/Python310/python.exe')
ROI_LABELS = ('nasal_cavity_left', 'nasal_cavity_right', 'nasopharynx', 'oropharynx')

# N6: the opening-area bands. Normal means inside; anything else escalates.
# oropharynx_truncation_outlet is an ENGINEERING TRUNCATION at the scan's
# inferior face, not an anatomical structure: its area is set by the scan FOV
# and has no anatomical reference band. So [10, 600] exists only to catch
# pathological failures (a clipped-away or runaway cap), NOT to validate
# anatomy - see T-058. The old nasopharynx band [120, 500] would escalate b15
# (112.51 mm2) purely for having been scanned with a smaller FOV.
AREA_BAND_MM2 = {'nostril_L': (40.0, 140.0), 'nostril_R': (40.0, 140.0),
                 'oropharynx_truncation_outlet': (10.0, 600.0)}
NORMAL_CASES = [f'b{i:02d}' for i in range(1, 25)]   # b25-b27 are multi-series


def run(cmd, timeout):
    t0 = time.time()
    try:
        p = subprocess.run([str(c) for c in cmd], capture_output=True, timeout=timeout,
                           text=True, encoding='utf-8', errors='replace')
        return {'rc': p.returncode, 's': round(time.time() - t0, 1),
                'tail': (p.stdout or '')[-300:] + (p.stderr or '')[-300:]}
    except subprocess.TimeoutExpired:
        return {'rc': None, 's': round(time.time() - t0, 1), 'why': 'timeout'}
    except Exception as exc:
        return {'rc': None, 's': round(time.time() - t0, 1),
                'why': f'{type(exc).__name__}: {exc}'}


def artifact_sha(path):
    """sha256 of a build artifact, or None when it is missing.

    Recorded per case in the run JSON so a number can always be traced back to
    the exact geometry that produced it. The 2026-10-13 investigation of the
    b02 outlet 268.51 -> 177.44 change burned hours because the run records
    kept only rc/s/tail: nothing said which surface and which landmarks a run
    had actually read, and the per-case reports are overwritten by every later
    batch, so they cannot serve as the durable record either.
    """
    p = Path(path)
    if not p.is_file():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def mask_check(case):
    """N2: three labels present and non-empty."""
    import SimpleITK as sitk
    d = TS_BASE / case / 'masks'
    if not d.is_dir():
        return {'gate': 'N2', 'ok': False, 'why': 'no masks dir'}
    vox = {}
    for r in ROI_LABELS:
        f = d / f'{r}.nii.gz'
        if not f.is_file():
            return {'gate': 'N2', 'ok': False, 'why': f'{r} missing'}
        vox[r] = int((sitk.GetArrayFromImage(sitk.ReadImage(str(f))) > 0).sum())
    empty = [r for r, v in vox.items() if v == 0]
    return {'gate': 'N2', 'ok': not empty, 'voxels': vox,
            'why': f'empty labels {empty}' if empty else ''}


def gate_report(case, path, surface_sha=None, plane_sha=None):
    """N6: read the per-case report and check the opening band.

    When the caller passes the sha256 it fingerprinted for this run's surface and
    landmarks, they are cross-checked against the shas the placement report
    recorded for the files it actually read. A mismatch means stage 5 computed
    its numbers from different geometry than this run built - a stale file, a
    parallel case overwriting a shared path - and the areas below are not
    evidence about the artifacts named in this record.
    """
    if not path.is_file():
        return {'gate': 'N5', 'ok': False, 'why': 'no placement report'}
    rep = json.loads(path.read_text(encoding='utf-8'))
    provenance = {}
    for key, expect in (('surface', surface_sha), ('plane', plane_sha)):
        got = rep.get('source_sha256' if key == 'surface' else 'plane_source_sha256')
        if expect is None or got is None:
            provenance[key] = 'unrecorded'
        else:
            provenance[key] = 'match' if got == expect else 'MISMATCH'
    if rep.get('decision') != 'auto_pass':
        return {'gate': 'N6', 'ok': False, 'decision': rep.get('decision'),
                'escalations': rep.get('escalations'), 'provenance': provenance}
    areas = rep.get('patch_areas_mm2') or {}
    out = {}
    for name, (lo, hi) in AREA_BAND_MM2.items():
        a = areas.get(name)
        if a is None or not lo <= a <= hi:
            out[name] = a
    return {'gate': 'N6', 'ok': not out, 'decision': 'auto_pass',
            'areas_mm2': areas, 'outside_band': out or None,
            'provenance': provenance}


def cpu_load_percent():
    """Whole-machine CPU load, 0-100, or None if it cannot be read.

    This is the machine's total load including everything else the user is
    running, which is the number that matters: the ceiling is a share of the
    whole machine, not of this script.
    """
    try:
        import ctypes

        class FILETIME(ctypes.Structure):
            _fields_ = [('dwLowDateTime', ctypes.c_uint32),
                        ('dwHighDateTime', ctypes.c_uint32)]

        def ft(v):
            return (v.dwHighDateTime << 32) | v.dwLowDateTime

        idle, kern, user = FILETIME(), FILETIME(), FILETIME()
        ok = ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
        if not ok:
            return None
        time.sleep(0.25)
        i2, k2, u2 = FILETIME(), FILETIME(), FILETIME()
        ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(i2), ctypes.byref(k2), ctypes.byref(u2))
        di = ft(i2) - ft(idle)
        dt = (ft(k2) - ft(kern)) + (ft(u2) - ft(user))
        return None if dt <= 0 else round(100.0 * (1.0 - di / float(dt)), 1)
    except Exception:
        return None


def wait_for_headroom(ceiling, poll=3.0, max_wait=900.0):
    """Block until machine load is below `ceiling`. Returns the load on exit.

    This is the closed-loop half of the governor. Checking only once before a
    burst of submits does not work: the submits complete instantly, so eight
    cases all start while the machine still reads low, and the load then climbs
    past the ceiling with nothing left to stop it. Measured that mistake: an
    8-wide run hit 100% before settling at 76%. Therefore this is called before
    *every* submit, and the pool is sized so that a steady state under the
    ceiling is reachable.

    Returns None if the load cannot be read; we do not stall forever on a number
    we cannot obtain."""
    if ceiling is None:
        return None
    waited, load = 0.0, None
    while waited < max_wait:
        load = cpu_load_percent()
        if load is None or load < ceiling:
            return load
        time.sleep(poll)
        waited += poll
    return load


def run_case(case, args):
    e = {'case': case}
    seg = [PY, '-u', LIB / 'ts_nasal_seg.py', '--batch-dir',
           ROOT / 'work' / '10_nasalseg_intake', '--device', args.device]
    if args.threads:
        seg += ['--threads', str(args.threads)]
    seg.append(case)
    e['s2_segment'] = run(seg, 7200)
    e['N2'] = mask_check(case)
    if not e['N2']['ok']:
        e['final'] = 'escalated'
        print(f'{case}: escalated at N2 - {e["N2"]["why"]}', flush=True)
        return e

    e['s3_propose'] = run([PY, '-u', LIB / 'auto_anatomy_landmarks.py', case,
                           '--data-base', TS_BASE], 1800)
    e['s3_propose']['landmarks_sha256'] = artifact_sha(
        ROOT / 'work' / '06_auto_landmarks' / case / 'landmarks.json')
    surface_root = Path(args.surface_root)
    opening_root = Path(args.opening_root)
    e['s4_surface'] = run([PY, '-u', LIB / 'batch27_surface.py', '--cases', case,
                           '--out', surface_root], 3600)
    e['s4_surface']['surface_sha256'] = artifact_sha(
        surface_root / case / 'source_surface.vtp')
    e['s5_place'] = run([PY, '-u', LIB / 'auto_opening_pipeline.py',
                         '--output', opening_root, '--proposals',
                         ROOT / 'work' / '06_auto_landmarks', '--src',
                         surface_root, '--cases', case]
                        + (['--allow-needs-review'] if args.allow_needs_review else [])
                        + (['--allow-onset-outlier'] if args.allow_onset_outlier else [])
                        + ['--seed-mode', args.seed_mode,
                           '--search-origin', args.search_origin],
                        5400)
    e['N6'] = gate_report(case, opening_root / f'{case}.json',
                          surface_sha=e['s4_surface'].get('surface_sha256'),
                          plane_sha=e['s3_propose'].get('landmarks_sha256'))
    # A provenance mismatch is not a soft warning: the areas were produced from
    # geometry this record does not describe, so they cannot be used as evidence.
    if 'MISMATCH' in (e['N6'].get('provenance') or {}).values():
        e['final'] = 'escalated'
        e['N6']['ok'] = False
        print(f"{case}: escalated - provenance {e['N6']['provenance']}", flush=True)
        return e
    e['final'] = 'auto_pass' if e['N6']['ok'] else 'escalated'
    print(f"{case}: {e['final']}  areas={e['N6'].get('areas_mm2')}"
          f"{'  ' + str(e['N6'].get('outside_band')) if e['N6'].get('outside_band') else ''}",
          flush=True)
    return e


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cases', nargs='+', default=None,
                    help='default: b01..b24, the normal single-series cases')
    ap.add_argument('--device', default='cpu')
    ap.add_argument('--skip-series', action='store_true')
    ap.add_argument('--jobs', type=int, default=1,
                    help='parallel cases; default 1 (serial). Raise deliberately: '
                         'each one keeps a core busy for the whole stage 2-5 chain')
    ap.add_argument('--threads', type=int, default=0,
                    help='cores one case may use during segmentation. 0 = leave it '
                         'to PyTorch, which defaults to every logical core and will '
                         'pin the whole machine. Set this before raising --jobs.')
    ap.add_argument('--load-ceiling', type=float, default=None,
                    help='pause new cases while whole-machine CPU load is above '
                         'this percent (e.g. 80). Unset means no governor.')
    ap.add_argument('--allow-needs-review', action='store_true',
                    help='admit auto proposals flagged needs_review at stage 5. '
                         'Recorded per case under admitted_needs_review. The only '
                         'flag that fires on this cohort is the soft_palate FOV '
                         'flag, which is a necessary condition misread as a '
                         'sufficient one - see auto_opening_pipeline.load_planes.')
    ap.add_argument('--seed-mode', choices=('roi', 'loop', 'hybrid'), default='roi',
                    help='how the connectivity flood is seeded at stage 5. '
                         'roi (default) = the reviewed ROI box, unchanged. '
                         'hybrid = box first, rim band when the box holds no '
                         'negative-side vertex (the measured seed_lost failure), '
                         'with every fallback recorded in the case report. '
                         'loop = rim band only; measured to also select '
                         'fragments belonging to other openings, so it is a '
                         'control arm, not a default.')
    ap.add_argument('--search-origin', choices=('onset', 'reviewed'), default='reviewed',
                    help='stage-5 placement search origin. reviewed (default since '
                         '2026-10-13) searches from the proposed plane (the '
                         'anatomical anchor) and only travels when the cap there is '
                         'under target; this removes the seed_lost coupling measured '
                         'on b05/b15/b18. onset is the historical behaviour, kept as '
                         'a control arm - the plane is searched from the detected '
                         'lumen onset, which couples placement to a 50 mm2 '
                         'detection threshold. See search_base().')
    ap.add_argument('--allow-onset-outlier', action='store_true',
                    help='demote the stage-5 onset_outlier gate to an advisory '
                         'flag (report key onset_flags). The gate blocks any '
                         'opening whose lumen onset sits outside [-4, +1] mm, a '
                         'band read off five pilot cases; it guarded the onset-'
                         'anchored search, which is no longer the default. See '
                         'auto_opening_pipeline --allow-onset-outlier for the '
                         'measured evidence. A missing onset still blocks.')
    ap.add_argument('--output', type=Path,
                    default=ROOT / 'work' / '10_nasalseg_intake' / 'normal_run.json')
    ap.add_argument('--surface-root', type=Path, default=SURFACE_ROOT,
                    help='where stage 4 writes source_surface.vtp (and, since '
                         'T-058, air_mask.nii.gz). Defaults to the production '
                         'root. Point it elsewhere to run a re-scoped batch '
                         'without overwriting the one already on disk.')
    ap.add_argument('--opening-root', type=Path, default=OPENING_ROOT,
                    help='where stage 5 writes the per-case placement reports. '
                         'Same rationale as --surface-root.')
    args = ap.parse_args()
    cases = args.cases or NORMAL_CASES
    rows = {}
    pre = {}

    # Stage 1 is per batch, not per case: it scans every DICOM directory once and
    # writes the single batch27_series_choice.json that stage 2 reads. It used to
    # sit inside the case loop, which re-scanned all 27 cases for every case.
    if not args.skip_series:
        pre['s1_series'] = run([PY, '-u', LIB / 'batch27_series_choice.py'], 1800)
        print(f"series choice rc={pre['s1_series']['rc']}"
              f" ({pre['s1_series']['s']}s)", flush=True)

    if args.jobs <= 1:
        for case in cases:
            load = wait_for_headroom(args.load_ceiling)
            if args.load_ceiling is not None:
                print(f'{case}: start (machine load {load}%)', flush=True)
            rows[case] = run_case(case, args)
    else:
        # Each task is its own subprocess chain, so a thread pool is enough: the
        # CPU cost lives in the child processes, not in these threads.
        #
        # Backpressure, not a burst: we wait for headroom before every single
        # submit and only ever have `jobs` in flight. A burst submit (the first
        # thing tried) let 8 cases start at 16% load and the machine then hit
        # 100%. With this shape the machine is checked, then one case is handed
        # out, then it is checked again.
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = {}
            spawned = 0
            for case in cases:
                # Keep at most `jobs` running: this is the real pacing. The load
                # governor then decides whether we are allowed to fill that slot.
                while len(futures) >= args.jobs:
                    done = [f for f in futures if f.done()]
                    for f in done:
                        c = futures.pop(f)
                        try:
                            rows[c] = f.result()
                        except Exception as exc:
                            rows[c] = {'case': c, 'final': 'escalated',
                                       'why': f'{type(exc).__name__}: {exc}'}
                            print(f'{c}: escalated - {rows[c]["why"]}', flush=True)
                    if len(futures) >= args.jobs:
                        time.sleep(2.0)
                load = wait_for_headroom(args.load_ceiling)
                if args.load_ceiling is not None:
                    print(f'{case}: start (load {load}%, in flight {len(futures)})',
                          flush=True)
                futures[pool.submit(run_case, case, args)] = case
                spawned += 1
            for f in as_completed(list(futures)):
                c = futures[f]
                try:
                    rows[c] = f.result()
                except Exception as exc:
                    rows[c] = {'case': c, 'final': 'escalated',
                               'why': f'{type(exc).__name__}: {exc}'}
                    print(f'{c}: escalated - {rows[c]["why"]}', flush=True)

    ok = sum(1 for r in rows.values() if r['final'] == 'auto_pass')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(
        {'schema': 'normal_path_run/v1', 'method': 'work/07_cfd_pipeline/正常路径基本方法_v1.md',
         'cases': len(rows), 'auto_pass': ok, 'jobs': args.jobs,
         'load_ceiling': args.load_ceiling, 'pre': pre, 'rows': rows},
        indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'\nauto_pass {ok}/{len(rows)}  -> {args.output}')


if __name__ == '__main__':
    main()