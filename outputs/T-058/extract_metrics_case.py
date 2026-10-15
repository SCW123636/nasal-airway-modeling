"""T-058 parameterized metrics extraction: one case's S-A solve -> M2 package.

Mirrors outputs/T-054/extract_metrics_b15.py exactly (same M2 four criteria,
same conventions), generalized to any case id.  Reads the staging dir
C:/ts_work/t058_chain/<case>/ which must contain:
  postProcessing/   (surfaceFieldValue monitors, copied from WSL)
  log.simpleFoam    (solver log, copied from WSL)
  maxh1.msh.mesh.json  (netgen mesh report: labelled patch areas + cell count)

Reconciliation targets (known answers):
  b15 -> T-054: dp 18.267 Pa, R 0.07307, cells 636342
  b01 -> T-047: dp 15.709 Pa, R 0.06284, cells 764801
  b02 -> fresh baseline (no prior answer)

Usage: python extract_metrics_case.py <case>
"""
import datetime
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

CASE = sys.argv[1] if len(sys.argv) > 1 else 'b15'
BASE = Path(f'C:/ts_work/t058_chain/{CASE}')
CASE_PP = BASE / 'postProcessing'
LOG = BASE / 'log.simpleFoam'
PROFILE = Path('D:/项目/鼻腔建模/outputs/T-048/airway_profile_throat.json')
OUT = BASE / f'metrics_t058_{CASE}_oroext.json'

RHO = 1.2
NU = 1.508333333333333e-05
MU = NU * RHO
Q_TOTAL = 2.5e-4
BAND_PA = (10.0, 100.0)
IMB_TOL = 0.005
MON_TOL = 0.005
WIN = 20
TAIL_FRAC = 0.6

KNOWN = {
    'b15': {'delta_p_pa': 18.267, 'R_pa_s_ml': 0.07307, 'cells': 636342,
            'src': 'T-054 b15 oropharynx-extended maxh1 S-A'},
    'b01': {'delta_p_pa': 15.709, 'R_pa_s_ml': 0.06284, 'cells': 764801,
            'src': 'T-047 b01 oropharynx-extended maxh1 S-A'},
}


def read_dat(path):
    t, v = [], []
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        try:
            t.append(float(parts[0]))
            v.append(float(parts[1]))
        except (ValueError, IndexError):
            continue
    return np.asarray(t), np.asarray(v)


def tail(x):
    n = max(2, int(len(x) * TAIL_FRAC))
    return x[-n:] if len(x) >= 2 else x


def load_mesh_report():
    """Netgen mesh report: labelled patch areas + cell count."""
    f = BASE / 'maxh1.msh.mesh.json'
    if not f.is_file():
        return None
    d = json.loads(f.read_text(encoding='utf-8'))
    return d


def main():
    data = {}
    for name in ('flowInL', 'flowInR', 'flowOut', 'pressureInL', 'pressureInR', 'pressureOut'):
        d = CASE_PP / name
        dat_files = sorted(d.glob('**/*.dat'))
        if not dat_files:
            raise SystemExit(f'missing monitor data for {name} under {d}')
        ts, vs = [], []
        for f in dat_files:
            t, v = read_dat(f)
            ts.append(t)
            vs.append(v)
        t = np.concatenate(ts)
        v = np.concatenate(vs)
        order = np.argsort(t)
        data[name] = (t[order], v[order])

    p_in_l = float(tail(data['pressureInL'][1]).mean())
    p_in_r = float(tail(data['pressureInR'][1]).mean())
    p_out = float(tail(data['pressureOut'][1]).mean())
    q_in_l = float(tail(data['flowInL'][1]).mean())
    q_in_r = float(tail(data['flowInR'][1]).mean())
    q_out = float(tail(data['flowOut'][1]).mean())

    q_in = abs(q_in_l + q_in_r)
    imbalance = abs(q_in_l + q_in_r + q_out) / q_in if q_in else float('nan')
    dp_kin = (p_in_l + p_in_r) / 2.0 - p_out
    dp_pa = dp_kin * RHO
    r_pa_s_ml = dp_pa / (q_in * 1e6) if q_in else float('nan')

    t_ref = data['pressureInL'][0]
    n = len(t_ref)
    start = int(n * TAIL_FRAC)
    dp_series = RHO * ((data['pressureInL'][1] + data['pressureInR'][1]) / 2.0
                       - np.interp(t_ref, data['pressureOut'][0], data['pressureOut'][1]))
    windows = [dp_series[i:i + WIN].mean() for i in range(start, n - WIN + 1, WIN)]
    if len(windows) >= 2:
        changes = [abs(windows[i + 1] - windows[i]) / abs(windows[i])
                   for i in range(len(windows) - 1) if abs(windows[i]) > 0]
        mon_max = max(changes) if changes else 0.0
    else:
        mon_max = None

    log_text = LOG.read_text(encoding='utf-8', errors='replace') if LOG.is_file() else ''
    times = [float(m.group(1)) for m in re.finditer(r'^Time = (\d+)', log_text, re.M)]
    last_time = int(times[-1]) if times else 0
    fatal = any(('FOAM FATAL' in l)
                or ('Floating point exception' in l and 'trapping' not in l)
                or ('sigFPE' in l and 'FOAM_SIGFPE' not in l)
                for l in log_text.splitlines())
    end_clean = bool(re.search(r'^End\s*$', log_text, re.M))
    res = {}
    for fld in ('Ux', 'p'):
        m = re.findall(rf'Solving for {fld}[^\n]*Initial residual = ([\d.eE+-]+)', log_text)
        res[fld] = float(m[-1]) if m else None

    # analytical increment over the visible oropharynx (T-048 per-case profile)
    dp_seg = None
    if PROFILE.is_file():
        prof = json.loads(PROFILE.read_text(encoding='utf-8'))['cases'].get(CASE)
        if prof:
            i_sup = prof['oro_label_superior_k'] - prof['oro_label_inferior_k']
            areas_m2 = [a * 1e-6 for a in prof['area_mm2'][:i_sup + 1]]
            z = prof['z_mm'][:i_sup + 1]
            dz = [abs(z[k + 1] - z[k]) * 1e-3 for k in range(len(z) - 1)] + [0.0]
            dp_seg = sum(8.0 * math.pi * MU * Q_TOTAL * d / (a * a)
                         for a, d in zip(areas_m2, dz) if a > 0)

    mesh = load_mesh_report()
    areas_mesh = (mesh or {}).get('patch_areas_mm2') or {}
    cells = (mesh or {}).get('tetrahedra')

    m2 = {
        'no_crash': bool(end_clean and not fatal and last_time >= 600),
        'delta_p_in_band_10_100Pa': bool(BAND_PA[0] <= dp_pa <= BAND_PA[1]),
        'mass_imbalance_le_0.5pct': bool(imbalance <= IMB_TOL),
        'monitor_stable_le_0.5pct': (bool(mon_max <= MON_TOL) if mon_max is not None else None),
    }

    reconcile = None
    if CASE in KNOWN:
        k = KNOWN[CASE]
        reconcile = {
            'reference': k['src'],
            'delta_p_pa': {'known': k['delta_p_pa'], 'now': round(dp_pa, 3),
                           'rel_diff': (dp_pa - k['delta_p_pa']) / k['delta_p_pa']},
            'R_pa_s_ml': {'known': k['R_pa_s_ml'], 'now': round(r_pa_s_ml, 5),
                          'rel_diff': (r_pa_s_ml - k['R_pa_s_ml']) / k['R_pa_s_ml']},
            'cells': {'known': k['cells'], 'now': cells},
        }

    report = {
        'created': datetime.datetime.now().astimezone().isoformat(),
        'task': f'T-058 {CASE} oropharynx-extended S-A solve metrics (production chain)',
        'schema': 'nasal_cfd_metrics/v1',
        'solver': 'laminar (simpleFoam S-A preset, mirrors T-006/T-042/T-054)',
        'rho_kg_m3': RHO,
        'boundary_convention': 'fixed 50:50 nostril flow split (1.25e-4 m3/s each) '
                               '+ outlet p=0 gauge; comparable ONLY with T-006/T-041/T-042/'
                               'T-047/T-054, NOT with T-021/T-029 common-static-pressure runs',
        'outlet_role': 'engineering_truncation_at_scan_inferior_face; downstream '
                       '(hypopharynx+larynx) resistance missing -> delta_p biased low',
        'domain': {'labels': 'nasal_cavity_left+right+nasopharynx+oropharynx',
                   'mesh_cells_repaired': cells},
        'samples': {'monitor_points': int(n), 'last_time': last_time,
                    'steady_window': f'last {100 - TAIL_FRAC * 100:.0f}%'},
        'metrics': {
            'converged': False,
            'numerical_validation': 'unchecked (per M2 ruling; final residuals recorded)',
            'final_initial_residuals': res,
            'delta_p_pa': {'value': dp_pa,
                           'p_inL_kinematic': p_in_l, 'p_inR_kinematic': p_in_r,
                           'p_out_kinematic': p_out,
                           'note': 'mean of bilateral inlet area-average p, x rho'},
            'total_flow_m3s': {'value': q_in, 'target': Q_TOTAL},
            'outlet_flow_m3s': {'value': q_out},
            'mass_imbalance_frac': imbalance,
            'monitor_max_window_change_frac': mon_max,
            'resistance_R': {'value_pa_s_ml': r_pa_s_ml,
                             'value_pa_s_m3': r_pa_s_ml * 1e6 if r_pa_s_ml == r_pa_s_ml else None},
        },
        'extension_increment': {
            'analytical_oropharynx_segment_dp_pa': dp_seg,
            'method': 'Poiseuille integral over T-048 per-case area profile '
                      '(8*pi*mu*Q*SUM(dz/A^2)); laminar straight-tube lower bound',
        },
        'm2_criteria': m2,
        'patch_areas_mm2': {'mesh_labelled': areas_mesh},
        'reconciliation': reconcile,
        'clinical_status': 'generalisation_test_only_no_human_review',
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')

    print(f"== {CASE} ==")
    print(f"last_time={last_time} end_clean={end_clean} fatal={fatal}")
    print(f"dp = {dp_pa:.3f} Pa  (band 10-100: {m2['delta_p_in_band_10_100Pa']})")
    print(f"Q_in = {q_in:.4e} (target {Q_TOTAL:.2e}); Q_out = {q_out:.4e}")
    print(f"imbalance = {imbalance:.3e} (<=0.5%: {m2['mass_imbalance_le_0.5pct']})")
    print(f"monitor max window change = {mon_max if mon_max is None else f'{mon_max:.3e}'}")
    print(f"R = {r_pa_s_ml:.5f} Pa.s/mL")
    if dp_seg is not None:
        print(f"analytical oropharynx segment dp = {dp_seg:.3f} Pa")
    print(f"cells = {cells}")
    print(f"M2: {m2}")
    if reconcile:
        print('reconciliation:', json.dumps(reconcile, ensure_ascii=False))
    print('written:', OUT)


if __name__ == '__main__':
    main()
