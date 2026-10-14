"""Compare two auto_opening_pipeline runs case by case, on the same axis.

Two classes of rule, deliberately kept apart:

  (A) arm-agnostic invariants - always checked, never hardcoded per arm:
      * every case that passed in the baseline must stay bit-identical in area
        (if a change moves a passing case, it did more than it claims);
      * no case may go auto_pass -> escalated ("newly failing").

  (B) arm-specific expectations - declared on the command line, NOT baked in.

Historically this file hardcoded ANCHOR_FAILED = {b04, b23} on the premise that
both were "anchor failures" (onset_outlier). That premise was falsified on
2026-10-13: b23's onset_outlier is not an anchor error - its reviewed-anchored
search reaches an in-band cap (87.97/80.45/276.87 mm2), while b04 still fails
for a real reason (seed_lost) once the onset gate stops masking it. A tool that
keeps asserting a falsified premise turns a correct change into a "FAIL", which
is how you learn to ignore your own gate. So the expectation is now an argument:

  --expect-pass      cases that MUST become auto_pass          (default: none)
  --expect-blocked   cases that MUST NOT become auto_pass
                     (default: historical b04/b23/b20, see HISTORICAL_*)
  --reasons-clean    escalated cases whose reported reason must no longer be
                     onset_outlier - i.e. the gate stopped masking the truth

Anything listed in --expect-pass is removed from the blocked set, so a caller
cannot accidentally assert both.

Usage:
  python ab_compare_runs.py <baseline.json> <candidate.json> [options]
"""
import argparse
import json
from pathlib import Path

HISTORICAL_BLOCKED = {'b04', 'b23'}   # onset_outlier, read as "anchor failed"
HISTORICAL_NO_POINT = {'b20'}         # nostril_L unavailable - nothing to seed


def load(path):
    d = json.loads(Path(path).read_text(encoding='utf-8'))
    return d['rows'] if isinstance(d, dict) and 'rows' in d else d


def reasons(row):
    out = []
    for e in row.get('N6', {}).get('escalations', []):
        out.append((e.get('opening'), e.get('reason')))
    return out


def _cases(text):
    return {c.strip() for c in (text or '').split(',') if c.strip()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('baseline')
    ap.add_argument('candidate')
    ap.add_argument('--expect-pass', default='',
                    help='comma list that MUST become auto_pass')
    ap.add_argument('--expect-blocked', default=None,
                    help='comma list that MUST NOT become auto_pass; '
                         'default is the historical anchor-failure set')
    ap.add_argument('--reasons-clean', default='',
                    help='comma list of escalated cases whose reason must no '
                         'longer be onset_outlier')
    ap.add_argument('--no-blocked-defaults', action='store_true',
                    help='start the blocked set empty instead of the historical one')
    args = ap.parse_args(argv)

    expect_pass = _cases(args.expect_pass)
    reasons_clean = _cases(args.reasons_clean)
    if args.expect_blocked is not None:
        blocked = _cases(args.expect_blocked)
    elif args.no_blocked_defaults:
        blocked = set()
    else:
        blocked = set(HISTORICAL_BLOCKED) | set(HISTORICAL_NO_POINT)
    blocked -= expect_pass

    base, cand = load(args.baseline), load(args.candidate)
    print(f'{"case":6s} {"baseline":>10s} {"candidate":>10s}  {"changed":<7s} '
          f'baseline reasons / candidate reasons')
    n_b = n_c = 0
    for k in sorted(base):
        rb, rc = base[k], cand.get(k)
        fb = rb['final']
        fc = rc['final'] if rc else 'MISSING'
        n_b += fb == 'auto_pass'
        n_c += fc == 'auto_pass'
        mark = 'YES' if fb != fc else ''
        rr = ', '.join(f'{o}:{r}' for o, r in reasons(rb)) or '-'
        rc_ = ', '.join(f'{o}:{r}' for o, r in reasons(rc)) if rc else '-'
        print(f'{k:6s} {fb:>10s} {fc:>10s}  {mark:<7s} {rr} / {rc_}')
    print(f'\nauto_pass: baseline {n_b}/{len(base)}  candidate {n_c}/{len(cand)}')

    print('\n--- area identity (rule 1: previously passing must stay bit-identical) ---')
    area_bad = []
    for k in sorted(base):
        if base[k]['final'] != 'auto_pass':
            continue
        ab = base[k].get('N6', {}).get('areas_mm2')
        ac = cand.get(k, {}).get('N6', {}).get('areas_mm2') if k in cand else None
        if ab != ac:
            area_bad.append((k, ab, ac))
    n_pass_base = sum(1 for k in base if base[k]['final'] == 'auto_pass')
    if area_bad:
        for k, ab, ac in area_bad:
            print(f'  {k}: MISMATCH  {ab} -> {ac}')
    else:
        print(f'  all {n_pass_base} previously passing cases: areas bit-identical  OK')

    print('\n--- acceptance rules ---')
    ok = True
    ok &= not area_bad
    for k in sorted(blocked):
        v = cand[k]['final'] if k in cand else 'MISSING'
        good = v != 'auto_pass'
        ok &= good
        print(f'  {k} (expected blocked) must NOT pass: {v}  '
              f'{"OK" if good else "VIOLATION"}')
    for k in sorted(expect_pass):
        v = cand[k]['final'] if k in cand else 'MISSING'
        good = v == 'auto_pass'
        ok &= good
        print(f'  {k} (expected to pass) must pass: {v}  '
              f'{"OK" if good else "VIOLATION"}')
    for k in sorted(reasons_clean):
        rs = [r for _, r in reasons(cand.get(k) or {})]
        good = 'onset_outlier' not in rs
        ok &= good
        print(f'  {k} reason must not be onset_outlier: {rs or "auto_pass"}  '
              f'{"OK" if good else "VIOLATION"}')
    lost = [k for k in sorted(base)
            if base[k]['final'] == 'auto_pass' and k in cand
            and cand[k]['final'] != 'auto_pass']
    print(f'  previously passing cases now failing: {lost or "none"}'
          f'{"   <== REGRESSION" if lost else ""}')
    print(f'\nverdict: {"PASS" if ok and not lost else "FAIL"}')


if __name__ == '__main__':
    main()
