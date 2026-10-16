# -*- coding: utf-8 -*-
"""T-058 anatomical-cut chain verification (3 cases: b15/b01/b02).

Aggregates per-case artefacts produced by chain_case_anat.sh + collect_chain_anat.sh
and decides the card's acceptance table:

  A. chain completion        : chain.log reaches CHAIN-DONE <case>
  B. mesh gates             : cells / max non-orthogonality / max aspect ratio /
                              failed checks (checkMesh.log)
  C. M2 four criteria       : from metrics_t058_<case>_oroext.json (m2_criteria)
  D. outlet area accounting : mesh-labelled areas, axial -> anatomical delta
                              (EXPECTED to change: the cut rule changed)
  E. nostril regression     : opening-stage nostril areas vs the short-domain
                              production values (b15 80.04/80.06, b01 80.08/80.08,
                              b02 80.15/80.22) - the inlet side must NOT move
  F. WSS                    : force / median / max (wss_t058_<case>.json)

Honest framing: b15/b01 numbers are NOT expected to reproduce the axial-cut
baselines (T-054 / T-047) - the outlet geometry changed by construction. The
axial baselines are listed side by side as口径历史参考.

Usage: python verify_anat_chain.py [chain_root]
Writes: outputs/T-058/anat_chain_verification.json
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('C:/ts_work/t058_chain_anat')
HERE = Path(__file__).resolve().parent
OUT = HERE / 'anat_chain_verification.json'
CASES = ('b15', 'b01', 'b02')

# 开口阶段鼻孔面积 = 短域生产值（T-042/T-047/T-054 已审基线），扩展域不得改动
NOSTRIL_KNOWN = {
    'b15': (80.04, 80.06), 'b01': (80.08, 80.08), 'b02': (80.15, 80.22),
}
# 轴位切基线（历史参考，本卡不要求复现）
AXIAL_BASELINE = {
    'b15': {'src': 'T-054', 'dp_pa': 18.267, 'R': 0.07307, 'wss_force_n': 1.506e-3,
            'outlet_mesh_mm2': 112.505258, 'cells': 636342},
    'b01': {'src': 'T-047', 'dp_pa': 15.709, 'R': 0.06284, 'wss_force_n': 1.331e-3,
            'outlet_mesh_mm2': None, 'cells': 764801},
    'b02': None,
}


def parse_checkmesh(text):
    g = lambda pat, cast=float: (lambda m: cast(m.group(1)) if m else None)(
        re.search(pat, text))
    det_lines = [l.strip() for l in text.splitlines() if 'determinant' in l.lower()]
    det_small = None
    m = re.search(r'(\d+)\s*(?:cells|faces).*determinant', text, re.I)
    if m:
        det_small = int(m.group(1))
    return {
        'cells': g(r'cells:\s+(\d+)', int),
        'points': g(r'points:\s+(\d+)', int),
        'non_orth_max': g(r'Mesh non-orthogonality Max:\s*([\d.]+)'),
        'non_orth_avg': g(r'Mesh non-orthogonality Max:\s*[\d.]+\s*average:\s*([\d.]+)'),
        'aspect_max': g(r'Max aspect ratio\s*=\s*([\d.]+)'),
        'failed_checks': g(r'Failed\s+(\d+)\s+mesh check', int),
        'mesh_ok': bool(re.search(r'^Mesh OK\.', text, re.M)),
        'determinant_lines': det_lines[:4],
        'det_small_count': det_small,
    }


def main():
    rep = {'task': 'T-058 anatomical-cut 3-case chain verification',
           'chain_root': str(ROOT),
           'cut_convention': 'anatomical_oblique_perpendicular_to_local_airway_axis',
           'cases': {}, 'summary': {}}

    for c in CASES:
        d = ROOT / c
        entry = {}
        chain_log = (d / 'chain.log').read_text(encoding='utf-8', errors='replace') \
            if (d / 'chain.log').is_file() else ''
        entry['chain_done'] = f'CHAIN-DONE {c}' in chain_log
        entry['collect_done'] = (d / 'postProcessing').is_dir()

        cm = d / 'checkMesh.log'
        entry['checkmesh'] = parse_checkmesh(
            cm.read_text(encoding='utf-8', errors='replace')) if cm.is_file() else None

        mf = d / f'metrics_t058_{c}_oroext.json'
        wx = d / f'wss_t058_{c}.json'
        met = json.loads(mf.read_text(encoding='utf-8')) if mf.is_file() else None
        wss = json.loads(wx.read_text(encoding='utf-8')) if wx.is_file() else None
        entry['metrics'] = met
        entry['wss'] = wss

        mesh_j = d / 'maxh1.msh.mesh.json'
        mj = json.loads(mesh_j.read_text(encoding='utf-8')) if mesh_j.is_file() else {}
        areas_open = mj.get('opening_stage_areas_mm2') or {}
        areas_mesh = mj.get('boundary_patch_areas_mm2') or {}

        # E. 鼻孔回归（开口阶段值）。NOSTRIL_KNOWN 是四舍五入到 2 位的展示值，
        #    必须容差比较：逐位相等的判据只适用于同一批浮点产物，不适用于
        #    跨批的重网结果（实际 80.03741 vs 展示 80.04）。
        nk = NOSTRIL_KNOWN[c]
        tol = 0.01  # mm^2；远小于任何有解剖意义的开口面积变化
        nL, nR = areas_open.get('nostril_L'), areas_open.get('nostril_R')
        entry['nostril_regression'] = {
            'known': list(nk),
            'now': [nL, nR],
            'tolerance_mm2': tol,
            'delta': [None if nL is None else round(nL - nk[0], 4),
                      None if nR is None else round(nR - nk[1], 4)],
            'match': bool(nL is not None and nR is not None
                          and abs(nL - nk[0]) <= tol and abs(nR - nk[1]) <= tol),
        }

        # D. 出口面积口径变化
        ax = AXIAL_BASELINE.get(c)
        entry['outlet_area'] = {
            'opening_stage_mm2': areas_open.get('oropharynx_truncation_outlet'),
            'mesh_labelled_mm2': areas_mesh.get('oropharynx_truncation_outlet'),
            'axial_mesh_labelled_mm2': (ax or {}).get('outlet_mesh_mm2'),
            'rel_change_vs_axial': (
                None if not ax or not ax.get('outlet_mesh_mm2')
                else (areas_mesh.get('oropharynx_truncation_outlet', 0)
                      - ax['outlet_mesh_mm2']) / ax['outlet_mesh_mm2']),
        }
        entry['axial_baseline'] = ax
        rep['cases'][c] = entry

    # 汇总
    s = {'all_chain_done': all(rep['cases'][c]['chain_done'] for c in CASES),
         'all_collected': all(rep['cases'][c]['collect_done'] for c in CASES),
         'all_nostril_match': all(rep['cases'][c]['nostril_regression']['match']
                                  for c in CASES),
         'm2_by_case': {}, 'cells_by_case': {}}
    for c in CASES:
        m = rep['cases'][c]['metrics'] or {}
        s['m2_by_case'][c] = m.get('m2_criteria')
        s['cells_by_case'][c] = ((rep['cases'][c]['checkmesh'] or {}).get('cells')
                                 or (m.get('domain') or {}).get('mesh_cells_repaired'))
    s['all_m2_pass'] = all(
        (cr or {}).get('no_crash') and (cr or {}).get('delta_p_in_band_10_100Pa')
        and (cr or {}).get('mass_imbalance_le_0.5pct')
        and (cr or {}).get('monitor_stable_le_0.5pct') is not False
        for cr in s['m2_by_case'].values())
    rep['summary'] = s

    OUT.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding='utf-8')

    print('case | chain | cells   | nonorth | aspect | failed | dp(Pa) | R      | WSS N    | nostril')
    for c in CASES:
        e = rep['cases'][c]
        cm = e['checkmesh'] or {}
        m = (e['metrics'] or {}).get('metrics') or {}
        w = e['wss'] or {}
        dp = (m.get('delta_p_pa') or {}).get('value')
        r = (m.get('resistance_R') or {}).get('value_pa_s_ml')
        print(f"{c}    | {str(e['chain_done'])[:5]:5} | {(cm.get('cells') or 0):7} | "
              f"{(cm.get('non_orth_max') or 0):7.2f} | {(cm.get('aspect_max') or 0):6.1f} | "
              f"{(cm.get('failed_checks') if cm.get('failed_checks') is not None else 0):6} | "
              f"{(dp if dp is not None else float('nan')):6.3f} | "
              f"{(r if r is not None else float('nan')):6.5f} | "
              f"{(w.get('wall_shear_force_n') or float('nan')):.4e} | "
              f"{'OK' if e['nostril_regression']['match'] else 'MISMATCH'}")
    print()
    print('summary:', json.dumps(rep['summary'], ensure_ascii=False))
    print('written:', OUT)


if __name__ == '__main__':
    main()
