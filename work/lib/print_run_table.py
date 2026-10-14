"""Print a per-case result table from a normal_run_*.json batch file.

Usage: python work/lib/print_run_table.py <run.json> [<run.json> ...]

Read-only. Exists because the baseline table in the method doc has to be
regenerated from the actual run file every time the default changes - the
"baseline value mixed across pipelines" accident happened exactly because a
number was carried over by hand.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auto_opening_pipeline import AREA_BAND_MM2, OPENINGS  # noqa: E402


def rows_of(path):
    d = json.loads(Path(path).read_text(encoding='utf-8'))
    return d['rows'] if isinstance(d, dict) and 'rows' in d else d


def main(paths):
    for path in paths:
        rows = rows_of(path)
        print(f'### {path}')
        print('| case | final | nostril_L | nostril_R | outlet | band | downgrade |')
        print('|---|---|---|---|---|---|---|')
        npass = 0
        for c in sorted(rows):
            r = rows[c]
            n6 = r.get('N6') or {}
            a = n6.get('areas_mm2') or {}
            if r.get('final') == 'auto_pass':
                npass += 1
            if not a:
                print(f'| {c} | {r.get("final")} | - | - | - | - | - |')
                continue
            flags = [n for n in OPENINGS
                     if not AREA_BAND_MM2[n][0] <= a[n] <= AREA_BAND_MM2[n][1]]
            band = 'OK' if not flags else 'OUT:' + ','.join(flags)
            dg = 'YES' if n6.get('origin_downgrade') else ''
            print(f'| {c} | {r.get("final")} | {a["nostril_L"]:.2f} | '
                  f'{a["nostril_R"]:.2f} | {a["nasopharynx_outlet"]:.2f} | '
                  f'{band} | {dg} |')
        print(f'auto_pass: {npass}/{len(rows)}\n')


if __name__ == '__main__':
    main(sys.argv[1:])
