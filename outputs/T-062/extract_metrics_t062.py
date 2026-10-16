"""T-062 自然分流口径指标提取：一个 eval 的收敛场 -> M2 包。

镜像 outputs/T-058/extract_metrics_case.py（同 M2 四项判据、同口径约定），仅两处不同：
  1. 监测目录名 = `flow_<patch>` / `pressure_<patch>`（set_pressure_boundaries 的命名），
     而非生产链的 flowInL/flowOut/...；
  2. 口径声明 = **共同静压自然分流**（与固定 50:50 不是同一个量），
     对账基准改为同几何同网格的 T-058 解剖切 50:50 生产跑（foam_maxh1/600）。

读盘：<stage_root>/<case>/ 下须有
  postProcessing/  log.simpleFoam  maxh1.msh.mesh.json  （+.vtp 供 WSS 用另一脚本）

用法：python extract_metrics_t062.py <case> [stage_root]
"""
import datetime
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

CASE = sys.argv[1] if len(sys.argv) > 1 else 'b15'
ROOT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('C:/ts_work/t062_natural')
BASE = ROOT / CASE
CASE_PP = BASE / 'postProcessing'
LOG = BASE / 'log.simpleFoam'
PROFILE = Path('D:/项目/鼻腔建模/outputs/T-048/airway_profile_throat.json')
OUT = BASE / f'metrics_t062_{CASE}_natural.json'

RHO = 1.2
NU = 1.508333333333333e-05
MU = NU * RHO
Q_TOTAL = 2.5e-4
BAND_PA = (10.0, 100.0)
IMB_TOL = 0.005
MON_TOL = 0.005
WIN = 20
TAIL_FRAC = 0.6
END_TIME = 600

INLETS = ('nostril_L', 'nostril_R')
OUTLET = 'oropharynx_truncation_outlet'
MON = [('flow', n) for n in (*INLETS, OUTLET)] + [('pressure', n) for n in (*INLETS, OUTLET)]

# 对账基准 = 同几何同网格的 T-058 解剖切 50:50 生产跑（2026-10-16 实测）
KNOWN_5050 = {
    'b15': {'delta_p_pa': 17.114, 'R_pa_s_ml': 0.06846, 'cells': 653789,
            'src': 'T-058 anatomical-cut b15 50:50 baseline foam_maxh1/600',
            'p_inL_kin': 14.074, 'p_inR_kin': 14.454},
    'b01': {'delta_p_pa': 15.460, 'R_pa_s_ml': 0.06184, 'cells': None,
            'src': 'T-058 anatomical-cut b01 50:50 baseline (patient_metrics.json)'},
    'b02': {'delta_p_pa': 43.231, 'R_pa_s_ml': 0.17292, 'cells': None,
            'src': 'T-058 anatomical-cut b02 50:50 baseline (patient_metrics.json)'},
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


def load_monitors():
    data = {}
    for kind, name in MON:
        key = f'{kind}_{name}'
        d = CASE_PP / key
        dat_files = sorted(d.glob('**/*.dat'))
        if not dat_files:
            raise SystemExit(f'missing monitor data for {key} under {d}')
        ts, vs = [], []
        for f in dat_files:
            t, v = read_dat(f)
            ts.append(t)
            vs.append(v)
        t = np.concatenate(ts)
        v = np.concatenate(vs)
        order = np.argsort(t)
        data[key] = (t[order], v[order])
    return data


def main():
    data = load_monitors()

    p_in_l = float(tail(data['pressure_nostril_L'][1]).mean())
    p_in_r = float(tail(data['pressure_nostril_R'][1]).mean())
    p_out = float(tail(data[f'pressure_{OUTLET}'][1]).mean())
    q_in_l = float(tail(data['flow_nostril_L'][1]).mean())
    q_in_r = float(tail(data['flow_nostril_R'][1]).mean())
    q_out = float(tail(data[f'flow_{OUTLET}'][1]).mean())

    q_in = abs(q_in_l + q_in_r)
    imbalance = abs(q_in_l + q_in_r + q_out) / q_in if q_in else float('nan')
    # 自然分流：两入口共同静压 → 用面积加权（此处两侧面积不等，权重按实测面积）
    a_l, a_r = (8.258142282973e-05, 8.119556123941e-05)  # nostril_L / nostril_R 实测面积
    p_in = (p_in_l * a_l + p_in_r * a_r) / (a_l + a_r)
    dp_pa = (p_in - p_out) * RHO
    r_pa_s_ml = dp_pa / (q_in * 1e6) if q_in else float('nan')
    left_fraction = abs(q_in_l) / q_in if q_in else float('nan')

    t_ref = data['pressure_nostril_L'][0]
    n = len(t_ref)
    start = int(n * TAIL_FRAC)
    dp_series = RHO * (np.interp(t_ref, data['pressure_nostril_L'][0], data['pressure_nostril_L'][1])
                       - np.interp(t_ref, data[f'pressure_{OUTLET}'][0], data[f'pressure_{OUTLET}'][1]))
    windows = [dp_series[i:i + WIN].mean() for i in range(start, n - WIN + 1, WIN)]
    mon_max = None
    if len(windows) >= 2:
        changes = [abs(windows[i + 1] - windows[i]) / abs(windows[i])
                   for i in range(len(windows) - 1) if abs(windows[i]) > 0]
        mon_max = max(changes) if changes else 0.0

    # 流量监测窗间变化（M2 监测口径，出口流量）
    q_series = data[f'flow_{OUTLET}'][1]
    qw = [q_series[i:i + WIN].mean() for i in range(start, n - WIN + 1, WIN)]
    q_mon_max = None
    if len(qw) >= 2:
        ch = [abs(qw[i + 1] - qw[i]) / abs(qw[i]) for i in range(len(qw) - 1) if abs(qw[i]) > 0]
        q_mon_max = max(ch) if ch else 0.0

    log_text = LOG.read_text(encoding='utf-8', errors='replace') if LOG.is_file() else ''
    times = [float(m.group(1)) for m in re.finditer(r'^Time = (\d+)', log_text, re.M)]
    last_time = int(times[-1]) if times else 0
    fatal = any(('FOAM FATAL' in l) for l in log_text.splitlines())
    end_clean = bool(re.search(r'^End\s*$', log_text, re.M))
    res = {}
    for fld in ('Ux', 'p'):
        m = re.findall(rf'Solving for {fld}[^\n]*Initial residual = ([\d.eE+-]+)', log_text)
        res[fld] = float(m[-1]) if m else None

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

    mesh_file = BASE / 'maxh1.msh.mesh.json'
    mesh = json.loads(mesh_file.read_text(encoding='utf-8')) if mesh_file.is_file() else None
    cells = (mesh or {}).get('tetrahedra')

    m2 = {
        'no_crash': bool(end_clean and not fatal and last_time >= END_TIME),
        'delta_p_in_band_10_100Pa': bool(BAND_PA[0] <= dp_pa <= BAND_PA[1]),
        'mass_imbalance_le_0.5pct': bool(imbalance <= IMB_TOL),
        'monitor_stable_le_0.5pct': (bool(mon_max <= MON_TOL) if mon_max is not None else None),
        'flow_monitor_stable_le_0.5pct': (bool(q_mon_max <= MON_TOL) if q_mon_max is not None else None),
    }

    reconcile = None
    if CASE in KNOWN_5050:
        k = KNOWN_5050[CASE]
        reconcile = {
            'reference': k['src'],
            'note': '自然分流 vs 固定 50:50 —— **不同口径、不同量**，只作量级对照，'
                    '不作同一序列比较；预期可合并量（占比类 / 双侧 R）差异 <2%（Borojeni 2017），'
                    '单侧/区域 WSS 可显著（Taylor 2010）。',
            'delta_p_pa': {'known': k['delta_p_pa'], 'now': round(dp_pa, 3),
                           'rel_diff': (dp_pa - k['delta_p_pa']) / k['delta_p_pa']},
            'R_pa_s_ml': {'known': k['R_pa_s_ml'], 'now': round(r_pa_s_ml, 5),
                          'rel_diff': (r_pa_s_ml - k['R_pa_s_ml']) / k['R_pa_s_ml']},
            'left_fraction_natural': round(left_fraction, 4),
            'cells': k['cells'],
        }

    report = {
        'created': datetime.datetime.now().astimezone().isoformat(),
        'task': f'T-062 {CASE} natural-split (common inlet static pressure) M2 metrics',
        'schema': 'nasal_cfd_metrics/v1',
        'solver': 'laminar simpleFoam; T-062 stabilised pressure-driven settings '
                  '(consistent no, relTol 0.01, U 0.4, p 0.15)',
        'rho_kg_m3': RHO,
        'boundary_convention': 'COMMON bilateral inlet static pressure (natural split, '
                               'no forced 50:50) + oropharynx truncation outlet p=0 gauge; '
                               'outer iteration drives Q_total -> 250 mL/s. NOT the same '
                               'quantity as the fixed-50:50 runs (T-054/T-047/T-058).',
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
                           'note': 'area-weighted mean of bilateral inlet area-average p, x rho'},
            'total_flow_m3s': {'value': q_in, 'target': Q_TOTAL,
                               'rel_error': (q_in - Q_TOTAL) / Q_TOTAL},
            'outlet_flow_m3s': {'value': q_out},
            'left_fraction': left_fraction,
            'mass_imbalance_frac': imbalance,
            'monitor_max_window_change_frac': mon_max,
            'flow_monitor_max_window_change_frac': q_mon_max,
            'resistance_R': {'value_pa_s_ml': r_pa_s_ml,
                             'value_pa_s_m3': r_pa_s_ml * 1e6 if r_pa_s_ml == r_pa_s_ml else None},
        },
        'extension_increment': {
            'analytical_oropharynx_segment_dp_pa': dp_seg,
            'method': 'Poiseuille integral over T-048 per-case area profile '
                      '(8*pi*mu*Q*SUM(dz/A^2)); laminar straight-tube lower bound',
        },
        'm2_criteria': m2,
        'reconciliation_50_50_vs_natural': reconcile,
        'clinical_status': 'generalisation_test_only_no_human_review',
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')

    print(f"== {CASE} natural split ==")
    print(f"last_time={last_time} end_clean={end_clean} fatal={fatal}")
    print(f"dp = {dp_pa:.3f} Pa  (band 10-100: {m2['delta_p_in_band_10_100Pa']})")
    print(f"Q_in = {q_in:.4e} (target {Q_TOTAL:.2e}, rel err {(q_in-Q_TOTAL)/Q_TOTAL:+.3%})")
    print(f"left_fraction = {left_fraction:.4f}")
    print(f"imbalance = {imbalance:.3e} (<=0.5%: {m2['mass_imbalance_le_0.5pct']})")
    print(f"monitor dp change = {mon_max}  flow change = {q_mon_max}")
    print(f"R = {r_pa_s_ml:.5f} Pa.s/mL")
    print(f"M2: {m2}")
    print('written:', OUT)


if __name__ == '__main__':
    main()
