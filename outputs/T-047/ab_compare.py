"""T-047 step 6 (A/B): b01 SHORT vs EXTENDED domain metrics comparison.

The only clean way to quantify the oropharynx extension's effect: same case
(b01), same netgen version + meshing params, same S-A preset, same boundary
convention (50:50 + outlet p=0). The ONLY difference is the domain:
  short    = nasal + nasopharynx, outlet = nasopharynx cap 251.73 mm2
  extended = + oropharynx (40 mm), outlet = scan-bottom truncation 148.93 mm2

Reads both postProcessing copies under C:/ts_work and writes ab_compare_t047.json.
"""
import datetime
import json
import math
import re
from pathlib import Path

import numpy as np

RHO = 1.2
MU = 1.508333333333333e-05 * RHO
Q_TOTAL = 2.5e-4
WIN = 20
TAIL_FRAC = 0.6
BAND_PA = (10.0, 100.0)

ARMS = {
    'short': {
        'pp': Path('C:/ts_work/t047_b01_short/postProcessing'),
        'log': Path('C:/ts_work/t047_b01_short/log.simpleFoam'),
        'outlet': 'nasopharynx_outlet',
        'outlet_area_mm2_mesh': None,   # filled from its mesh report if present
        'domain_volume_m3': None,
    },
    'extended': {
        'pp': Path('C:/ts_work/t047_b01_oroext/postProcessing'),
        'log': Path('C:/ts_work/t047_b01_oroext/log.simpleFoam'),
        'outlet': 'oropharynx_truncation_outlet',
        'outlet_area_mm2_mesh': 152.015274,
        'domain_volume_m3': 2.803989454244437e-05,
    },
}

PROFILE = Path('D:/项目/鼻腔建模/outputs/T-048/airway_profile_throat.json')
OUT = Path(__file__).resolve().parent / 'ab_compare_t047.json'


def read_dat(path):
    t, v = [], []
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        s = line.split()
        try:
            t.append(float(s[0]))
            v.append(float(s[1]))
        except (ValueError, IndexError):
            continue
    return np.asarray(t), np.asarray(v)


def tail(x):
    n = max(2, int(len(x) * TAIL_FRAC))
    return x[-n:] if len(x) >= 2 else x


def arm_metrics(arm):
    pp = arm['pp']
    data = {}
    for name in ('flowInL', 'flowInR', 'flowOut', 'pressureInL', 'pressureInR', 'pressureOut'):
        files = sorted((pp / name).glob('**/*.dat'))
        if not files:
            raise SystemExit(f'{arm["outlet"]}: missing {name} data')
        ts, vs = [], []
        for f in files:
            t, v = read_dat(f)
            ts.append(t)
            vs.append(v)
        t = np.concatenate(ts)
        v = np.concatenate(vs)
        o = np.argsort(t)
        data[name] = (t[o], v[o])
    p_l = float(tail(data['pressureInL'][1]).mean())
    p_r = float(tail(data['pressureInR'][1]).mean())
    p_o = float(tail(data['pressureOut'][1]).mean())
    q_l = float(tail(data['flowInL'][1]).mean())
    q_r = float(tail(data['flowInR'][1]).mean())
    q_o = float(tail(data['flowOut'][1]).mean())
    q_in = abs(q_l + q_r)
    imb = abs(q_l + q_r + q_o) / q_in
    dp_pa = RHO * ((p_l + p_r) / 2.0 - p_o)
    r_ml = dp_pa / (q_in * 1e6)
    n = len(data['pressureInL'][0])
    start = int(n * TAIL_FRAC)
    dp_s = RHO * ((data['pressureInL'][1] + data['pressureInR'][1]) / 2.0
                  - np.interp(data['pressureInL'][0], data['pressureOut'][0], data['pressureOut'][1]))
    wins = [dp_s[i:i + WIN].mean() for i in range(start, n - WIN + 1, WIN)]
    mon = (max(abs(wins[i + 1] - wins[i]) / abs(wins[i]) for i in range(len(wins) - 1))
           if len(wins) >= 2 else None)
    log_text = arm['log'].read_text(encoding='utf-8', errors='replace') if arm['log'].is_file() else ''
    times = [float(m.group(1)) for m in re.finditer(r'^Time = (\d+)', log_text, re.M)]
    fatal = any(('FOAM FATAL' in l) or ('Floating point exception' in l and 'trapping' not in l)
                for l in log_text.splitlines())
    end_clean = bool(re.search(r'^End\s*$', log_text, re.M))
    res = {}
    for fld in ('Ux', 'p'):
        m = re.findall(rf'Solving for {fld}[^\n]*Initial residual = ([\d.eE+-]+)', log_text)
        res[fld] = float(m[-1]) if m else None
    return {'samples': n, 'last_time': int(times[-1]) if times else 0,
            'end_clean': end_clean, 'fatal': fatal,
            'delta_p_pa': dp_pa, 'p_inL_pa': RHO * p_l, 'p_inR_pa': RHO * p_r,
            'mass_imbalance_frac': imb, 'monitor_max_window_change_frac': mon,
            'resistance_R_pa_s_ml': r_ml, 'final_initial_residuals': res,
            'outlet_mean_velocity_mps': (q_in / (arm['outlet_area_mm2_mesh'] * 1e-6)
                                         if arm['outlet_area_mm2_mesh'] else None)}


def main():
    results = {name: arm_metrics(cfg) for name, cfg in ARMS.items()}

    # analytical increment (visible oropharynx segment, b01 profile)
    prof = json.loads(PROFILE.read_text(encoding='utf-8'))['cases']['b01']
    i_sup = prof['oro_label_superior_k'] - prof['oro_label_inferior_k']
    areas_m2 = [a * 1e-6 for a in prof['area_mm2'][:i_sup + 1]]
    z = prof['z_mm'][:i_sup + 1]
    dz = [abs(z[k + 1] - z[k]) * 1e-3 for k in range(len(z) - 1)] + [0.0]
    dp_seg = sum(8.0 * math.pi * MU * Q_TOTAL * d / (a * a)
                 for a, d in zip(areas_m2, dz) if a > 0)

    ds, de = results['short'], results['extended']
    inc = de['delta_p_pa'] - ds['delta_p_pa']
    report = {
        'created': datetime.datetime.now().astimezone().isoformat(),
        'task': 'T-047 b01 short-vs-extended domain A/B',
        'boundary_convention': 'fixed 50:50 + outlet p=0; comparable with T-006/T-041/T-042 only',
        'arms': {name: {**{k: v for k, v in cfg.items() if k not in ('pp', 'log')},
                        'metrics': results[name]} for name, cfg in ARMS.items()},
        'increment': {
            'delta_p_extended_minus_short_pa': inc,
            'analytical_oropharynx_segment_pa': dp_seg,
            'analytical_method': 'Poiseuille integral 8*pi*mu*Q*SUM(dz/A^2) over T-048 b01 '
                                 'area profile (laminar straight-tube; curvature -> lower bound)',
            'resistance_increment_pa_s_ml': (de['resistance_R_pa_s_ml'] - ds['resistance_R_pa_s_ml']),
        },
        'interpretation': 'extension moves the artificial p=0 boundary ~40 mm downstream '
                          '(nasopharynx -> scan-bottom truncation); expected dp increase is '
                          'small (~0.25 Pa analytical) because the oropharynx is wide',
        'clinical_status': 'generalisation_test_only_no_human_review',
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')

    print(f"{'arm':10} {'time':>5} {'dp Pa':>8} {'R Pa.s/mL':>10} {'imb':>9} {'mon':>9} {'fatal':>6}")
    for name in ('short', 'extended'):
        m = results[name]
        mon = m['monitor_max_window_change_frac']
        print(f"{name:10} {m['last_time']:>5} {m['delta_p_pa']:>8.3f} {m['resistance_R_pa_s_ml']:>10.5f} "
              f"{m['mass_imbalance_frac']:>9.2e} {mon if mon is None else format(mon, '.2e'):>9} {str(m['fatal']):>6}")
    print(f"increment dp = {inc:+.3f} Pa (analytical segment {dp_seg:.3f} Pa)")
    print('written:', OUT)


if __name__ == '__main__':
    main()
