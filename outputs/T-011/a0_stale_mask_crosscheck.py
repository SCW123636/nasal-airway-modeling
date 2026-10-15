"""T-011 附带实验：把「掩码过期」这个病因放到 21 个 auto_pass 例上量一量。

目的（只读，不改任何生产文件）：Q4 的修法若改成「每个平面在当前网格上重算掩码」，
会不会动到其余通过的例？本项目有过一次「悄悄改了 4 个原本通过的例」的教训
（auto_opening_pipeline.py:240-246），所以这里用实测而不是推断。

做法：取 b01/b02/b21/b22/b23（都是 recorded auto_pass，且是历史上有位移的例），
用各例**已记录的 offset_from_reviewed_mm** 复现生产的 placed 平面，然后跑两种语义：
  A 生产语义：掩码在原始表面上算一次（clip_areas 第124行），顺序套用
  B 诊断语义：每个平面在自己的当前网格上重算同一个连通性掩码
比较：逐平面 outside_plane / maxdev、是否报错、最终三个开的 cap 面积，
      并把 A 与 C:\\ts_work\\batch27_opening\\<case>.json 里记录的面积对照（自校验）。

注意：offset 取报告里 2 位小数，与生产精确值可能差 ≤0.005 mm，因此面积对照允许极小偏差。

用法：
  C:/Users/lenovo/AppData/Local/Programs/Python/Python310/python.exe \
      "D:/项目/鼻腔建模/outputs/T-011/a0_stale_mask_crosscheck.py"
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding='utf-8', errors='replace')

import numpy as np  # noqa: E402

OUT = Path(r'D:\项目\鼻腔建模\outputs\T-011')
sys.path.insert(0, str(OUT))
from a0_clip_root_cause_probe import (  # noqa: E402
    OPENINGS, ROOT, TOL, build_placed, flood_mask, load_planes, load_surface_bare,
    plane_basis, replica_clip, topology,
)

CASES = ['b01', 'b02', 'b21', 'b22', 'b23']
SURFACE_ROOT = Path('C:/ts_work/batch27_surfaces')
REPORT_ROOT = Path('C:/ts_work/batch27_opening')
OUT_JSON = OUT / 'a0_stale_mask_crosscheck.json'


def main() -> int:
    result = {'cases': {}, 'note': 'offset 取报告 2 位小数；A=生产语义(掩码只算一次)，'
                                   'B=每个平面在当前网格上重算掩码'}
    for case in CASES:
        entry = {}
        rec = json.loads((REPORT_ROOT / f'{case}.json').read_text(encoding='utf-8'))
        entry['recorded'] = {'decision': rec.get('decision'),
                             'patch_areas_mm2': rec.get('patch_areas_mm2'),
                             'offset_from_reviewed_mm': rec.get('offset_from_reviewed_mm')}
        planes, prov, sha, admitted = load_planes(
            ROOT / 'work' / '06_auto_landmarks', None, case, allow_needs_review=True)
        pts, fcs = load_surface_bare(SURFACE_ROOT / case / 'source_surface.vtp')
        qc, _ = topology(pts, fcs)
        entry['surface'] = {'n_vertices': int(len(pts)), 'n_triangles': int(len(fcs)),
                            'boundary_edges': int(qc['boundary_edges'])}
        norms = {k: plane_basis(planes[k]['normal_lps'])[0] for k in OPENINGS}
        off = {k: float(rec['offset_from_reviewed_mm'][k]) for k in OPENINGS}
        placed = build_placed(planes, norms, {k: 0.0 for k in OPENINGS}, off)
        entry['used_offsets_mm'] = off
        sel = {}
        for k in OPENINGS:
            try:
                m, note = flood_mask(pts, fcs, placed[k], seed_mode='roi')
                sel[k] = m
                entry.setdefault('seeds', {})[k] = {
                    'seed_vertices': note['seed_vertices'], 'true_count': int(m.sum())}
            except ValueError as exc:
                entry.setdefault('seeds', {})[k] = {'raised': str(exc)}
        for tag, kw in (('A_production_masks_computed_once', dict(selectors=sel)),
                        ('B_masks_recomputed_each_plane',
                         dict(selectors=sel, recompute_mask=True))):
            try:
                r = replica_clip(pts, fcs, placed, tolerance_mm=TOL, order=list(OPENINGS),
                                 tag=tag, **kw)
            except BaseException as exc:  # noqa: BLE001
                r = {'replica_exception': f'{type(exc).__name__}: {exc}',
                     'trace': traceback.format_exc().splitlines()[-5:]}
            entry[tag] = {
                'raised': r.get('replica_raised'),
                'exception': r.get('replica_exception'),
                'patch_areas_mm2': r.get('patch_areas_mm2'),
                'per_plane': [{'plane': t.get('plane'), 'mask_origin': t.get('mask_origin'),
                               'mask_true': t.get('mask_true_count'),
                               'outside_plane': t.get('outside_plane'),
                               'outside_roi': t.get('outside_roi'),
                               'maxdev_mm': t.get('boundary_max_abs_dev_mm'),
                               'bd_verts': t.get('n_boundary_verts'),
                               'raise198': t.get('production_line198_raises'),
                               'caps': t.get('n_cap_triangles')} for t in (r.get('trace') or [])],
            }
        entry['compare'] = {
            'A_vs_recorded': entry['A_production_masks_computed_once']['patch_areas_mm2'],
            'B_vs_A_changed': None,
        }
        a = entry['A_production_masks_computed_once']['patch_areas_mm2']
        b = entry['B_masks_recomputed_each_plane']['patch_areas_mm2']
        if a and b:
            entry['compare']['B_minus_A_mm2'] = {k: round(b[k] - a[k], 3)
                                                 for k in sorted(set(a) & set(b))}
            entry['compare']['B_vs_A_changed'] = bool(entry['compare']['B_minus_A_mm2'])
        result['cases'][case] = entry
        print(f'=== {case} ===')
        print(f'  recorded areas      : {entry["recorded"]["patch_areas_mm2"]}')
        print(f'  A(生产语义) areas   : {a}  raised={entry["A_production_masks_computed_once"]["raised"]}')
        print(f'  B(逐平面重算) areas : {b}  raised={entry["B_masks_recomputed_each_plane"]["raised"]}')
        print(f'  B-A                 : {entry["compare"].get("B_minus_A_mm2")}')
        for tag in ('A_production_masks_computed_once', 'B_masks_recomputed_each_plane'):
            for p in entry[tag]['per_plane']:
                print(f'    [{tag[0]}] {p["plane"]:18s} mask={p["mask_true"]:>7} '
                      f'out_plane={p["outside_plane"]} maxdev={p["maxdev_mm"]} '
                      f'bd_verts={p["bd_verts"]} raise198={p["raise198"]}')
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str),
                        encoding='utf-8')
    print(f'\nwrote {OUT_JSON}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
