"""Compare two batch runs where the candidate is an INTENTIONAL baseline change.

This is not the regression tool (that one is `ab_compare_runs.py`, which demands
bit-identical areas). A baseline change is expected to move areas; what matters
is whether every case still lands inside its anatomical band and whether the
failure set shrank for the right reason.

Usage:
    python ab_compare_baseline_change.py BASE.json CAND.json [--band ...]

Prints, per case: final-state transition, per-opening area before/after/delta,
and whether the candidate area is inside AREA_BAND_MM2. Then a verdict block:
  - cases that stay auto_pass (with the largest area drift)
  - cases that newly pass, and the reason they failed before
  - cases that newly fail, which is the dangerous direction and is always
    printed in full
  - cases that stay escalated, with both reasons side by side
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auto_opening_pipeline import AREA_BAND_MM2, OPENINGS  # noqa: E402

REASONS = ('seed_lost', 'clip_failed', 'gate_failed', 'onset_outlier',
           'placement_unverified', 'no_onset')


def load(path):
    d = json.loads(Path(path).read_text(encoding='utf-8'))
    return d['rows'] if isinstance(d, dict) and 'rows' in d else d


def case_view(row):
    n6 = row.get('N6') or {}
    return {
        'final': row.get('final'),
        'areas': n6.get('areas_mm2') or {},
        'reasons': [e.get('reason') for e in (n6.get('escalations') or [])],
        'search_origin': n6.get('search_origin'),
        'seed_mode': n6.get('seed_mode'),
    }


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    base_rows, cand_rows = load(sys.argv[1]), load(sys.argv[2])
    cases = sorted(set(base_rows) | set(cand_rows))

    stay, gained, lost, stuck = [], [], [], []
    print(f'{"case":5s} {"base":9s} {"cand":9s} {"drift(mm2) L / R / outlet":40s} band')
    print('-' * 92)
    for c in cases:
        b = case_view(base_rows[c]) if c in base_rows else {'final': 'MISSING'}
        k = case_view(cand_rows[c]) if c in cand_rows else {'final': 'MISSING'}
        drift = []
        for n in OPENINGS:
            a0, a1 = b.get('areas', {}).get(n), k.get('areas', {}).get(n)
            if a0 is None or a1 is None:
                drift.append('  --  ')
            else:
                drift.append(f'{a1 - a0:+7.2f}')
        # band verdict on the candidate areas
        bad = [n for n in OPENINGS
               if k.get('areas', {}).get(n) is not None
               and not AREA_BAND_MM2[n][0] <= k['areas'][n] <= AREA_BAND_MM2[n][1]]
        band = 'OK' if not bad else 'OUT:' + ','.join(
            f'{n.split("_")[-1]}={k["areas"][n]:.1f}' for n in bad)
        print(f'{c:5s} {str(b["final"]):9s} {str(k["final"]):9s} '
              f'{" / ".join(drift):40s} {band}')
        if b['final'] == 'auto_pass' and k['final'] == 'auto_pass':
            stay.append(c)
        elif b['final'] != 'auto_pass' and k['final'] == 'auto_pass':
            gained.append((c, b.get('reasons')))
        elif b['final'] == 'auto_pass' and k['final'] != 'auto_pass':
            lost.append((c, k.get('reasons')))
        else:
            stuck.append((c, b.get('reasons'), k.get('reasons')))

    print()
    print(f'auto_pass: base {len([c for c in cases if c in base_rows and case_view(base_rows[c])["final"] == "auto_pass"])}'
          f'/{len(cases)}   candidate {len(stay) + len(gained)}/{len(cases)}')
    print(f'  stay passing      : {len(stay)}  {stay}')
    print(f'  newly passing     : {len(gained)}')
    for c, why in gained:
        print(f'      {c}: was {why}')
    print(f'  NEWLY FAILING     : {len(lost)}   <-- the dangerous direction')
    for c, why in lost:
        print(f'      {c}: now {why}')
    print(f'  stay escalated    : {len(stuck)}')
    for c, b_why, k_why in stuck:
        print(f'      {c}: base {b_why} -> cand {k_why}')

    # the largest drift among the cases that stay passing, since those are the
    # ones a reviewer will ask about
    if stay:
        print('\nlargest area drift among the cases that stay auto_pass:')
        rows = []
        for c in stay:
            a0 = case_view(base_rows[c])['areas']
            a1 = case_view(cand_rows[c])['areas']
            for n in OPENINGS:
                if a0.get(n) is not None and a1.get(n) is not None:
                    rows.append((abs(a1[n] - a0[n]), c, n, a0[n], a1[n]))
        for d, c, n, a0, a1 in sorted(rows, reverse=True)[:8]:
            print(f'  {c} {n:20s} {a0:8.2f} -> {a1:8.2f}  ({a1 - a0:+7.2f})')

    verdict = 'PASS' if not lost else 'FAIL'
    print(f'\nverdict: {verdict}  '
          f'(newly failing: {len(lost)}; newly passing: {len(gained)})')
    return 0 if not lost else 1


if __name__ == '__main__':
    raise SystemExit(main())
