"""T-011 A.2 - parameterized metrics extraction for a threshold-axis solve.
Identical definitions to extract_metrics_p0_snappy.py (A.1 S-A); argv-driven:
  python extract_metrics_t.py <case_dir> <out_json> <label>
label e.g. "t350 (-350 x maxh1.0-snappyL3 x S-A)".
Run inside WSL with the system python3.
"""
import datetime
import json
import re
import sys
from pathlib import Path

import numpy as np

CASE = Path(sys.argv[1])
OUT = Path(sys.argv[2])
LABEL = sys.argv[3]
TAG = sys.argv[4] if len(sys.argv) > 4 else ''

CASE_PP = CASE / 'postProcessing'
LOG = CASE / 'log.simpleFoam'

RHO = 1.2
Q_TOTAL = 2.5e-4
BAND_PA = (10.0, 100.0)
IMB_TOL = 0.005
MON_TOL = 0.005
WIN = 20
TAIL_FRAC = 0.6

# per-threshold snappy mesh-labeled patch areas (mm^2), MEASURED from the
# foamToVTK boundary vtp files (patch_areas_vtp.py, same fan-triangulation as
# the WSS extractor); opening-stage areas from the split reports.
import json as _json

def _load(tag):
    p = Path(__file__).resolve().parent / ('patch_areas_%s.json' % tag)
    d = _json.loads(p.read_text())
    return d

AREAS = {tag: _load(tag) for tag in ('t350', 't400')}
AREAS_OPENING = {
    't350': {'nostril_L': 80.28, 'nostril_R': 80.37, 'oropharynx_truncation_outlet': 223.94},
    't400': {'nostril_L': 80.31, 'nostril_R': 80.22, 'oropharynx_truncation_outlet': 223.11},
}
MESH = {
    't350': {'cells': 190724, 'max_nonorthogonality_deg': 56.9455,
             'max_aspect_ratio': 6.0936, 'total_volume_m3': 2.94964434922e-05},
    't400': {'cells': 188584, 'max_nonorthogonality_deg': 56.2777,
             'max_aspect_ratio': 5.9394, 'total_volume_m3': 2.9107821016e-05},
}
A1_ANCHOR = {'source': 'T-011 A.1 p0 threshold -300, same snappy route',
             'delta_p_pa': 14.717508932947034, 'R_pa_s_ml': 0.058870035731788124,
             'wss_force_n': 1.008636e-3}


def read_dat(path):
    t, v = [], []
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        p = line.split()
        try:
            t.append(float(p[0])); v.append(float(p[1]))
        except (ValueError, IndexError):
            continue
    return t, v


def series(name):
    d = {}
    files = sorted((CASE_PP / name).glob('**/*.dat'))
    if not files:
        raise SystemExit('missing monitor %s under %s' % (name, CASE_PP / name))
    for f in files:
        for t, v in zip(*read_dat(f)):
            d[t] = v
    ts = np.array(sorted(d))
    return ts, np.array([d[t] for t in ts])


def tail(x):
    n = max(2, int(len(x) * TAIL_FRAC))
    return x[-n:]


def main():
    s = {n: series(n) for n in ('flowInL', 'flowInR', 'flowOut',
                                'pressureInL', 'pressureInR', 'pressureOut')}
    p_in_l, p_in_r, p_out = (float(tail(s[n][1]).mean())
                             for n in ('pressureInL', 'pressureInR', 'pressureOut'))
    q_l, q_r, q_out = (float(tail(s[n][1]).mean())
                       for n in ('flowInL', 'flowInR', 'flowOut'))

    q_in = abs(q_l + q_r)
    imbalance = abs(q_l + q_r + q_out) / q_in if q_in else float('nan')
    dp_kin = (p_in_l + p_in_r) / 2.0 - p_out
    dp_pa = dp_kin * RHO
    r_ml = dp_pa / (q_in * 1e6) if q_in else float('nan')

    t_ref = s['pressureInL'][0]
    n = len(t_ref)
    start = int(n * TAIL_FRAC)
    dp_series = RHO * ((s['pressureInL'][1] + s['pressureInR'][1]) / 2.0
                       - np.interp(t_ref, s['pressureOut'][0], s['pressureOut'][1]))
    wins = [dp_series[i:i + WIN].mean() for i in range(start, n - WIN + 1, WIN)]
    if len(wins) >= 2:
        ch = [abs(wins[i + 1] - wins[i]) / abs(wins[i])
              for i in range(len(wins) - 1) if abs(wins[i]) > 0]
        mon_max = max(ch) if ch else 0.0
    else:
        mon_max = None

    log = LOG.read_text(encoding='utf-8', errors='replace')
    times = [int(m.group(1)) for m in re.finditer(r'^Time = (\d+)', log, re.M)]
    last_time = times[-1] if times else 0
    fatal = any(('FOAM FATAL' in l) or ('Floating point exception' in l and 'trapping' not in l)
                for l in log.splitlines())
    end_clean = bool(re.search(r'^End\s*$', log, re.M))
    res = {}
    for fld in ('Ux', 'p'):
        m = re.findall(rf'Solving for {fld}[^\n]*Final residual = ([\d.eE+-]+)', log)
        if not m:
            m = re.findall(rf'Solving for {fld}[^\n]*Initial residual = ([\d.eE+-]+)', log)
        res[fld + '_final'] = float(m[-1]) if m else None

    m2 = {
        'no_crash': bool(end_clean and not fatal and last_time >= 600),
        'delta_p_in_band_10_100Pa': bool(BAND_PA[0] <= dp_pa <= BAND_PA[1]),
        'mass_imbalance_le_0.5pct': bool(imbalance <= IMB_TOL),
        'monitor_stable_le_0.5pct': (bool(mon_max <= MON_TOL) if mon_max is not None else None),
    }

    report = {
        'created': datetime.datetime.now().astimezone().isoformat(),
        'task': 'T-011 A.2 threshold-axis cell %s' % LABEL,
        'schema': 'nasal_cfd_metrics/v1',
        'solver': 'laminar simpleFoam S-A preset (A.1 templates verbatim)',
        'mesher': 'snappyHexMesh castellated+snap, level 3 (0.5 mm), addLayers off; '
                  'blockMesh box + refinement identical to A.1',
        'threshold_hu': int(TAG[1:]) * -1 if TAG.startswith('t') else None,
        'rho_kg_m3': RHO,
        'boundary_convention': 'fixed 50:50 nostril flow split (1.25e-4 m3/s each) '
                               '+ outlet p=0 gauge; comparable ONLY with '
                               'T-006/T-041/T-042/T-054, NOT with T-021/T-029 '
                               'common-static-pressure runs',
        'outlet_role': 'engineering_truncation at scan inferior face; downstream '
                       'resistance missing -> delta_p biased low',
        'domain': MESH.get(TAG, {}),
        'samples': {'monitor_points': int(n), 'last_time': last_time,
                    'steady_window': 'last 40%'},
        'metrics': {
            'converged': False,
            'numerical_validation': 'unchecked (per M2 ruling; final residuals recorded)',
            'final_residuals': res,
            'delta_p_pa': {'value': dp_pa, 'p_inL_kinematic': p_in_l,
                           'p_inR_kinematic': p_in_r, 'p_out_kinematic': p_out,
                           'note': 'mean of bilateral inlet area-average p, x rho'},
            'total_flow_m3s': {'value': q_in, 'target': Q_TOTAL},
            'outlet_flow_m3s': {'value': q_out},
            'mass_imbalance_frac': imbalance,
            'monitor_max_window_change_frac': mon_max,
            'resistance_R': {'value_pa_s_ml': r_ml,
                             'value_pa_s_m3': r_ml * 1e6 if r_ml == r_ml else None},
            'outlet_mean_velocity_mps': q_in / (AREAS[TAG]['oropharynx_truncation_outlet'] * 1e-6),
            'nostril_mean_velocity_mps': {
                'L': q_in / 2 / (AREAS[TAG]['nostril_L'] * 1e-6),
                'R': q_in / 2 / (AREAS[TAG]['nostril_R'] * 1e-6)},
        },
        'comparison_A1_anchor_t300': A1_ANCHOR,
        'm2_criteria': m2,
        'patch_areas_mm2': {'mesh_labelled': AREAS.get(TAG, {}),
                            'opening_stage': AREAS_OPENING.get(TAG, {})},
        'clinical_status': 'generalisation_test_only_no_human_review',
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')

    print('last_time=%d end_clean=%s fatal=%s  monitor_points=%d' % (last_time, end_clean, fatal, n))
    print('p_inL=%.5f p_inR=%.5f p_out=%.5f (kinematic)' % (p_in_l, p_in_r, p_out))
    print('dp = %.3f Pa   (band 10-100: %s)' % (dp_pa, m2['delta_p_in_band_10_100Pa']))
    print('Q_in = %.6e m3/s  Q_out = %.6e' % (q_in, q_out))
    print('imbalance = %.3e (<=0.5%%: %s)' % (imbalance, m2['mass_imbalance_le_0.5pct']))
    print('monitor max window change = %s' % (mon_max,))
    print('R = %.5f Pa.s/mL   (A.1 -300 anchor: 0.05887)' % r_ml)
    print('final residuals: %s' % res)
    print('M2: %s' % m2)
    print('written: %s' % OUT)


if __name__ == '__main__':
    main()
