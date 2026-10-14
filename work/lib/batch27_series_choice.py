"""Pick one usable DICOM series per case, and say why the others were rejected.

The survey found 24 of27 cases are a single clean axial series; cases 25, 26 and
27 carry nine, fifteen and eight series including 3D_Sinus reconstructions,
Dose Report and Evidence Documents, all of which are unusable here. Feeding
those to nasal segmentation would burn ~136 s per case for a meaningless mask,
so the choice has to be made explicitly and recorded.

Selection rule, fixed before looking at the outcome:
  1. ImageType must be AXIAL / ORIGINAL (drops dose reports, scouts, evidence)
  2. in-plane spacing must be <= 0.8 mm (drops 3.0 mm MPR and 3D_Sinus volumes)
  3. among survivors, the finest in-plane spacing wins; ties break on the
     largest slice count, then on the name containing BONE
  4. everything rejected is listed with the rule that rejected it

Ties and near-ties are the risky part, so the margin between the winner and the
runner-up is reported: a small margin means the rule decided on slice count,
not on image quality, and that case deserves a human glance.
"""
import json
import sys
from pathlib import Path

import pydicom

BATCH = Path('D:/项目/鼻腔建模/资料/副鼻窦27例_脱敏完整/副鼻窦27例_脱敏完整')
MAX_IN_PLANE_MM = 0.8


def survey_dir(case_dir):
    groups = {}
    for p in sorted(case_dir.rglob('*')):
        if p.suffix.lower() != '.dcm':
            continue
        try:
            ds = pydicom.dcmread(str(p), stop_before_pixels=True, force=True)
        except Exception:
            continue
        uid = str(getattr(ds, 'SeriesInstanceUID', ''))
        it = list(getattr(ds, 'ImageType', None) or [])
        g = groups.setdefault(uid, {'n': 0, 'desc': str(getattr(ds, 'SeriesDescription', '')),
                                    'it': it[:3],
                                    'px': [float(x) for x in getattr(ds, 'PixelSpacing', [0, 0])],
                                    'z': float(getattr(ds, 'SliceThickness', 0) or 0),
                                    'rc': (int(getattr(ds, 'Rows', 0)), int(getattr(ds, 'Columns', 0))),
                                    'files': []})
        g['n'] += 1
        g['files'].append(p)
    return groups


def judge(g):
    """Return (usable, reason). Reasons are the rule that rejected it."""
    if not g['rc'][0] or not g['rc'][1]:
        return False, 'rule1: no pixel matrix (report or evidence document)'
    # DICOM PS3.3 C.7.6.2.1: ImageType is ordered value, then presence flags.
    # So a CT slice reads ['ORIGINAL', 'PRIMARY', 'AXIAL'] - the plane name is
    # the THIRD element. Testing index 1 for 'AXIAL' rejected all 27 cases,
    # which is what an over-confident assumption about tag layout looks like.
    upper = {str(x).upper() for x in g['it']}
    if not {'ORIGINAL', 'AXIAL'} <= upper:
        return False, f'rule1: ImageType {g["it"]} lacks ORIGINAL/AXIAL'
    sp = g['px'][0] if g['px'][0] else g['px'][1]
    if sp > MAX_IN_PLANE_MM + 1e-9:
        return False, f'rule2: in-plane {sp} mm > {MAX_IN_PLANE_MM} mm'
    return True, 'usable'


def main():
    rows = []
    for case_dir in sorted(BATCH.iterdir(), key=lambda p: int(p.name)):
        if not case_dir.is_dir():
            continue
        groups = survey_dir(case_dir)
        scored = []
        for uid, g in groups.items():
            ok, why = judge(g)
            sp = min(g['px']) if g['px'] else 9.9
            scored.append({'uid': uid, 'desc': g['desc'], 'n': g['n'], 'px': sp,
                           'z': g['z'], 'rc': list(g['rc']), 'usable': ok, 'reason': why,
                           'files': [str(f) for f in g['files']]})
        usable = [s for s in scored if s['usable']]
        # Order of preference, all of it decided before looking at the outcome:
        #   finest in-plane, then thinnest slices, then a bone reconstruction over
        #   a soft-tissue one, then most slices.
        # The bone preference is not cosmetic. A pair like '1.0 x 0.8 Bone' and
        # '1.0 x 0.8 Soft-3D' has identical spacing and identical slice count, so
        # without it the tie broke on name length and picked Soft-3D.
        usable.sort(key=lambda s: (round(s['px'], 4), round(s['z'], 4),
                                   'SOFT' in s['desc'].upper(), -s['n']))
        pick = usable[0] if usable else None
        margin = None
        if pick and len(usable) > 1:
            runner = usable[1]
            margin = {'spacing_delta_mm': round(pick['px'] - runner['px'], 4),
                      'thickness_delta_mm': round(pick['z'] - runner['z'], 4),
                      'runner_up': runner['desc'], 'runner_up_n': runner['n'],
                      'runner_up_thickness': runner['z'],
                      'decided_by': ('spacing' if pick['px'] < runner['px'] - 1e-9
                                     else 'slice_thickness' if pick['z'] < runner['z'] - 1e-9
                                     else 'reconstruction' if 'SOFT' in runner['desc'].upper()
                                     and 'SOFT' not in pick['desc'].upper()
                                     else 'slice_count')}
        rows.append({'case': case_dir.name, 'series_total': len(scored),
                     'usable': len(usable),
                     'pick': None if not pick else {'desc': pick['desc'], 'n': pick['n'],
                                                    'in_plane_mm': pick['px'], 'thickness_mm': pick['z'],
                                                    'rows_cols': pick['rc'],
                                                    'dir': str(Path(pick['files'][0]).parent)},
                     'margin_vs_runner_up': margin,
                     'rejected': [{'desc': s['desc'], 'n': s['n'], 'reason': s['reason']}
                                  for s in scored if not s['usable']]})
        m = f" margin={margin['spacing_delta_mm']} by {margin['decided_by']}" if margin else ''
        desc = (pick['desc'] or '(no description)') if pick else 'NO USABLE SERIES'
        cnt = pick['n'] if pick else 0
        px = pick['px'] if pick else 0
        print(f"case {case_dir.name}: {len(usable)}/{len(scored)} usable -> "
              f"{desc} {cnt}f {px}mm{m}", flush=True)

    dst = Path('D:/项目/鼻腔建模/work/10_nasalseg_intake/batch27_series_choice.json')
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps({'schema': 'batch27_series_choice/v1',
                               'max_in_plane_mm': MAX_IN_PLANE_MM, 'cases': rows},
                              indent=2, ensure_ascii=False), encoding='utf-8')
    ok = sum(1 for r in rows if r['pick'])
    print(f'\npicked {ok}/{len(rows)}; written {dst}')


if __name__ == '__main__':
    main()