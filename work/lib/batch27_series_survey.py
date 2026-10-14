"""Which DICOM series in the 27-case batch are actually usable for nasal CFD?

The batch is not uniform: case 27 holds a Topogram, a 3.0 mm MPR and an
evidence-document folder alongside the real series. Feeding any of those to
nasal segmentation would waste ~136 s per case and produce a meaningless mask.

Selection rule, stated so it can be argued with: for each case, group the DICOM
files by (SeriesInstanceUID) and keep the group whose slices are ImageType=1
(original axial), whose in-plane spacing is the finest present, and whose slice
count is consistent with covering a head. Everything else is reported as
rejected with the reason, so a wrong pick is visible rather than silent.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pydicom

BATCH = Path('D:/项目/鼻腔建模/资料/副鼻窦27例_脱敏完整/副鼻窦27例_脱敏完整')


def describe(paths):
    rows = []
    for p in paths:
        try:
            ds = pydicom.dcmread(str(p), stop_before_pixels=True, force=True)
        except Exception as exc:
            rows.append({'file': p.name, 'read_error': str(exc)[:80]})
            continue
        t = getattr(ds, 'ImageType', None)
        rows.append({
            'file': p.name,
            'uid': str(getattr(ds, 'SeriesInstanceUID', '')),
            'desc': str(getattr(ds, 'SeriesDescription', '')),
            'image_type': list(t) if t is not None else None,
            'rows': int(getattr(ds, 'Rows', 0)),
            'cols': int(getattr(ds, 'Columns', 0)),
            'spacing': [float(x) for x in getattr(ds, 'PixelSpacing', [0, 0])],
            'thickness': float(getattr(ds, 'SliceThickness', 0) or 0),
        })
    return rows


def classify(rows):
    by_uid = {}
    for r in rows:
        if 'read_error' in r:
            continue
        by_uid.setdefault(r['uid'], []).append(r)

    groups = []
    for uid, g in by_uid.items():
        it = g[0]['image_type'] or []
        # PS3.3 C.7.6.2.1: ordered value first, then presence flags, so an axial
        # CT slice is ['ORIGINAL', 'PRIMARY', 'AXIAL'] - AXIAL is index 2.
        upper = {str(x).upper() for x in it}
        axial_original = {'ORIGINAL', 'AXIAL'} <= upper
        desc = {x['desc'] for x in g}
        groups.append({
            'uid': uid, 'n': len(g), 'series_descriptions': sorted(desc),
            'in_plane': sorted({tuple(x['spacing']) for x in g}),
            'rows_cols': sorted({(x['rows'], x['cols']) for x in g}),
            'slice_thickness': sorted({x['thickness'] for x in g}),
            'image_type_head': it[:3],
            'axial_original': axial_original,
        })
    return groups


def main():
    out = {'schema': 'batch27_series_survey/v1', 'cases': {}}
    for case_dir in sorted(BATCH.iterdir(), key=lambda p: int(p.name)):
        if not case_dir.is_dir():
            continue
        paths = sorted(case_dir.rglob('*'))
        paths = [p for p in paths if p.suffix.lower() == '.dcm']
        rows = describe(paths)
        groups = classify(rows)
        good = [g for g in groups if g['axial_original'] and g['rows'] and g['cols']]
        out['cases'][case_dir.name] = {
            'dcm_files': len(paths),
            'read_errors': sum(1 for r in rows if 'read_error' in r),
            'groups': groups,
            'candidate_groups': len(good),
            'note': 'not yet ranked; this is the inventory',
        }
        brief = ', '.join(f"{g['n']}f {g['rows_cols'][0]} {g['series_descriptions'][0][:22]!r}"
                          for g in groups)
        print(f"case {case_dir.name}: {len(paths)} dcm, {len(groups)} series -> {brief}",
              flush=True)
    dst = Path('D:/项目/鼻腔建模/work/10_nasalseg_intake/batch27_series_survey.json')
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    print('written', dst)


if __name__ == '__main__':
    main()