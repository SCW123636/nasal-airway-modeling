"""T-054 step 5: metrics extraction for the b15 oropharynx-extended S-A solve.

Reads the case's postProcessing monitors (surfaceFieldValue .dat files, copied
from WSL to C:/ts_work/t054_b15_oroext/postProcessing) and computes the M2
four-criteria package plus the extension increment accounting:

  1. no-crash          : log.simpleFoam reaches Time = 600, exit clean
  2. delta_p in band   : mean inlet area-average p (kinematic) * rho=1.2, steady
                         window = last 40% of samples; band 10-100 Pa (M2)
  3. mass imbalance    : |Q_in + Q_out| / Q_in <= 0.5%
  4. monitor stability : window-to-window relative change of delta_p, window
                         length 20, within the last 40% samples <= 0.5%
  residualControl convergence is recorded as unchecked per the M2 ruling.

Extension increment accounting (geometry-informed analytical anchor):
  Poiseuille integral over the T-048 measured area profile of the visible
  oropharynx: dp = 8*pi*mu*Q * SUM(dz / A_k^2)  (laminar straight-tube
  estimate; curvature makes it a lower bound, reported as such).

Patch areas used: the MESH-LABELLED areas (consistent with T-042's use of
mesh-side areas), recorded alongside the opening-stage anchors.

Output: metrics_t054_b15_oroext.json (+ stdout table).
"""
import datetime
import json
import math
import re
from pathlib import Path

import numpy as np

CASE_PP = Path('C:/ts_work/t054_b15_oroext/postProcessing')
LOG = Path('C:/ts_work/t054_b15_oroext/log.simpleFoam')
PROFILE = Path('D:/项目/鼻腔建模/outputs/T-048/airway_profile_throat.json')
OUT = Path(__file__).resolve().parent / 'metrics_t054_b15_oroext.json'

RHO = 1.2
NU = 1.508333333333333e-05
MU = NU * RHO
Q_TOTAL = 2.5e-4
BAND_PA = (10.0, 100.0)
IMB_TOL = 0.005
MON_TOL = 0.005
WIN = 20
TAIL_FRAC = 0.6          # keep last 40%

AREAS_MESH_LABELLED = {'nostril_L': 82.709414, 'nostril_R': 81.892548,
                       'oropharynx_truncation_outlet': 112.505258}
AREAS_OPENING_STAGE = {'nostril_L': 80.03741, 'nostril_R': 80.057289,
                       'oropharynx_truncation_outlet': 111.002814}

B15_REFERENCE = {'delta_p_pa': 10.294, 'R_pa_s_ml': 0.04114,
                 'mass_imbalance_frac': 5.27e-07,
                 'source': 'T-042/T-041 b15 maxh1 S-A short domain (nasal+nasopharynx); '
                           '10.294 = same-method extraction of the T-041 maxh1 arm',
                 'domain_note': 'short-domain outlet was nasopharynx 487.67 mm2 mesh area; '
                                'visible oropharynx only 10.0 mm, so short domain excluded it'}


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


def main():
    data = {}
    for name in ('flowInL', 'flowInR', 'flowOut', 'pressureInL', 'pressureInR', 'pressureOut'):
        d = CASE_PP / name
        dat_files = sorted(d.glob('**/*.dat'))
        if not dat_files:
            raise SystemExit(f'missing monitor data for {name} under {d}')
        # stitch all time dirs in order (fresh run: single dir)
        ts, vs = [], []
        for f in dat_files:
            t, v = read_dat(f)
            ts.append(t)
            vs.append(v)
        t = np.concatenate(ts)
        v = np.concatenate(vs)
        order = np.argsort(t)
        data[name] = (t[order], v[order])

    # steady-window means
    p_in_l = float(tail(data['pressureInL'][1]).mean())
    p_in_r = float(tail(data['pressureInR'][1]).mean())
    p_out = float(tail(data['pressureOut'][1]).mean())
    q_in_l = float(tail(data['flowInL'][1]).mean())
    q_in_r = float(tail(data['flowInR'][1]).mean())
    q_out = float(tail(data['flowOut'][1]).mean())

    q_in = abs(q_in_l + q_in_r)
    # signed-sum continuity: inlet phi is negative, outlet phi positive;
    # |Q_inL + Q_inR + Q_out| / Q_in (T-042 convention, 5.27e-7 on b15)
    imbalance = abs(q_in_l + q_in_r + q_out) / q_in if q_in else float('nan')
    dp_kin = (p_in_l + p_in_r) / 2.0 - p_out
    dp_pa = dp_kin * RHO
    r_pa_s_ml = dp_pa / (q_in * 1e6) if q_in else float('nan')

    # monitor stability: delta_p(t) = rho*(mean(p_inL,p_inR)-p_out); windowed on common time grid
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

    # crash / completion check from the log
    log_text = LOG.read_text(encoding='utf-8', errors='replace') if LOG.is_file() else ''
    times = [float(m.group(1)) for m in re.finditer(r'^Time = (\d+)', log_text, re.M)]
    last_time = int(times[-1]) if times else 0
    fatal = any(('FOAM FATAL' in l)
                or ('Floating point exception' in l and 'trapping' not in l)
                or ('sigFPE' in l and 'FOAM_SIGFPE' not in l)
                for l in log_text.splitlines())
    end_clean = bool(re.search(r'^End\s*$', log_text, re.M))
    # final residuals (record only)
    res = {}
    for fld in ('Ux', 'p'):
        m = re.findall(rf'Solving for {fld}[^\n]*Initial residual = ([\d.eE+-]+)', log_text)
        res[fld] = float(m[-1]) if m else None

    # analytical increment over the visible oropharynx (T-048 profile, b15)
    prof = json.loads(PROFILE.read_text(encoding='utf-8'))['cases']['b15']
    i_sup = prof['oro_label_superior_k'] - prof['oro_label_inferior_k']
    areas_m2 = [a * 1e-6 for a in prof['area_mm2'][:i_sup + 1]]  # label range only
    z = prof['z_mm'][:i_sup + 1]
    dz = [abs(z[k + 1] - z[k]) * 1e-3 for k in range(len(z) - 1)] + [0.0]
    dp_seg = sum(8.0 * math.pi * MU * Q_TOTAL * d / (a * a)
                 for a, d in zip(areas_m2, dz) if a > 0)

    m2 = {
        'no_crash': bool(end_clean and not fatal and last_time >= 600),
        'delta_p_in_band_10_100Pa': bool(BAND_PA[0] <= dp_pa <= BAND_PA[1]),
        'mass_imbalance_le_0.5pct': bool(imbalance <= IMB_TOL),
        'monitor_stable_le_0.5pct': (bool(mon_max <= MON_TOL) if mon_max is not None else None),
    }
    report = {
        'created': datetime.datetime.now().astimezone().isoformat(),
        'task': 'T-054 b15 oropharynx-extended S-A solve metrics',
        'schema': 'nasal_cfd_metrics/v1',
        'solver': 'laminar (simpleFoam S-A preset, mirrors T-006/T-042)',
        'rho_kg_m3': RHO,
        'boundary_convention': 'fixed 50:50 nostril flow split (1.25e-4 m3/s each) '
                               '+ outlet p=0 gauge; comparable ONLY with T-006/T-041/T-042, '
                               'NOT with T-021/T-029 common-static-pressure runs',
        'outlet_role': 'engineering_truncation_at_scan_inferior_face; downstream '
                       '(hypopharynx+larynx) resistance missing -> delta_p biased low',
        'domain': {'volume_m3': 2.157993246258525e-05,
                   'labels': 'nasal_cavity_left+right+nasopharynx+oropharynx',
                   'mesh_cells_repaired': 636342,
                   'det_lt_0.001_cells_repaired': 466,
                   'max_nonorthogonality_deg': 76.80},
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
            'outlet_mean_velocity_mps': (q_in / (AREAS_MESH_LABELLED['oropharynx_truncation_outlet'] * 1e-6)),
            'nostril_mean_velocity_mps': {
                'L': q_in / 2 / (AREAS_MESH_LABELLED['nostril_L'] * 1e-6),
                'R': q_in / 2 / (AREAS_MESH_LABELLED['nostril_R'] * 1e-6)},
        },
        'extension_increment': {
            'analytical_oropharynx_segment_dp_pa': dp_seg,
            'method': 'Poiseuille integral over T-048 b15 area profile '
                      '(8*pi*mu*Q*SUM(dz/A^2)); laminar straight-tube lower bound',
            'b15_short_domain_delta_p_pa_T042': 10.294,
            'mesh_density_caveat': 'extended mesh 636,342 cells vs short 1,161,194 '
                                    '(1.83x); T-041 bounds density confound <= ~1.2%',
        },
        'comparison_b15_T042': B15_REFERENCE,
        'm2_criteria': m2,
        'patch_areas_mm2': {'mesh_labelled': AREAS_MESH_LABELLED,
                            'opening_stage': AREAS_OPENING_STAGE},
        'clinical_status': 'generalisation_test_only_no_human_review',
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')

    print(f"last_time={last_time} end_clean={end_clean} fatal={fatal}")
    print(f"dp = {dp_pa:.3f} Pa  (band 10-100: {m2['delta_p_in_band_10_100Pa']})")
    print(f"Q_in = {q_in:.4e} m3/s (target {Q_TOTAL:.2e}); Q_out = {q_out:.4e}")
    print(f"imbalance = {imbalance:.3e} (<=0.5%: {m2['mass_imbalance_le_0.5pct']})")
    print(f"monitor max window change = {mon_max if mon_max is None else f'{mon_max:.3e}'}")
    print(f"R = {r_pa_s_ml:.5f} Pa.s/mL (b15: 0.04114)")
    print(f"analytical oropharynx segment dp = {dp_seg:.3f} Pa")
    print(f"M2: {m2}")
    print('written:', OUT)


if __name__ == '__main__':
    main()
