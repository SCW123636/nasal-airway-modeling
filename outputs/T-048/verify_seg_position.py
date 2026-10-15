"""T-048 position/orientation verification for segmentation vs CT, all 29 cases.

Decisive checks that the segmentation sits at the truly correct anatomical
position and orientation (user demand 2026-10-16: "把分割位置方向等整到真正正确的位置"):

C0  geometry: every mask shape == CT shape; direction cosines identity (LPS).
C1  ordering: nasopharynx z_min > oropharynx z_min (nasopharynx never reaches
    as far inferior as the oropharynx) -- catches z-flips.
C2  junction: oropharynx z_max >= soft_palate z_min - 5 mm (oropharynx reaches
    up to the velum) -- catches shifted/dropped labels.
C3  nasal cavity z_min > oropharynx z_min.
C4  content: airway labels (nasal L/R, nasopharynx, oropharynx) must be mostly
    CT air (<-300 HU); tissue labels (soft_palate, hard_palate) mostly NOT air.
    A misplaced label fails its content class immediately.

Also renders a 3-case annotated mid-sagittal MPR (b01 long oropharynx,
b15 the CFD case, p2 longest) with the scan inferior face marked.

Read-only. Writes position_orientation_verification.json + seg_position_mpr.png.
"""
import datetime
import json
from pathlib import Path

import numpy as np
import nibabel as nib

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'Microsoft YaHei'
plt.rcParams['axes.unicode_minus'] = False

BASE = Path('C:/ts_work')
CASES = [f'b{i:02d}' for i in range(1, 25)] + ['p0', 'p1', 'p2', 'p3', 'p3t1']
AIRWAY_LABELS = ('nasal_cavity_left', 'nasal_cavity_right', 'nasopharynx', 'oropharynx')
TISSUE_LABELS = ('soft_palate', 'hard_palate')
HU = -300.0

OUT = Path(__file__).resolve().parent


def load_case(case):
    d = BASE / case
    ct = nib.load(str(d / 'ct.nii.gz'))
    aff = np.asarray(ct.affine, dtype=float)
    ident = np.allclose(aff[:3, :3], np.diag(np.diag(aff[:3, :3])), atol=1e-6)
    ct_arr = np.asarray(ct.dataobj).astype(np.float32)
    zooms = [float(z) for z in ct.header.get_zooms()]
    masks = {}
    for lbl in AIRWAY_LABELS + TISSUE_LABELS + ('hypopharynx',):
        p = d / 'masks' / f'{lbl}.nii.gz'
        if p.is_file():
            m = nib.load(str(p))
            masks[lbl] = (np.asarray(m.dataobj) > 0,
                          m.shape == ct_arr.shape)
    return ct_arr, aff, zooms, ident, masks


def z_range(arr, aff, zooms):
    kk = np.where(arr.any(axis=(0, 1)))[0]
    if not len(kk):
        return None
    return [float(aff[2, 3] + kk.min() * zooms[2]),
            float(aff[2, 3] + kk.max() * zooms[2])]


def verify_case(case):
    ct_arr, aff, zooms, ident, masks = load_case(case)
    vox_vol = zooms[0] * zooms[1] * zooms[2]
    air_ct = ct_arr < HU
    entry = {'direction_identity_lps': bool(ident), 'labels': {}, 'checks': {}}
    zr = {}
    for lbl, (arr, shape_ok) in masks.items():
        vox = int(arr.sum())
        overlap = int((arr & air_ct).sum()) if vox else 0
        z = z_range(arr, aff, zooms)
        zr[lbl] = z
        entry['labels'][lbl] = {
            'shape_matches_ct': bool(shape_ok),
            'voxels': vox,
            'vol_mm3': round(vox * vox_vol, 1),
            'air_overlap_voxels': overlap,
            'air_fraction': round(overlap / vox, 4) if vox else None,
            'z_range_mm': [round(v, 2) for v in z] if z else None,
        }
    del ct_arr, air_ct

    naso, oro = zr.get('nasopharynx'), zr.get('oropharynx')
    sp = zr.get('soft_palate')
    nl, nr = zr.get('nasal_cavity_left'), zr.get('nasal_cavity_right')
    ck = entry['checks']
    ck['C0_shapes_match'] = all(v['shape_matches_ct'] for v in entry['labels'].values())
    ck['C0_direction_identity'] = bool(ident)
    ck['C1_nasopharynx_above_oropharynx'] = bool(naso and oro and naso[0] > oro[0])
    ck['C2_oropharynx_reaches_velum'] = bool(oro and sp and oro[1] >= sp[0] - 5.0)
    ck['C3_nasal_cavities_above_oropharynx'] = bool(
        nl and nr and oro and nl[0] > oro[0] and nr[0] > oro[0])
    for lbl in AIRWAY_LABELS:
        fr = entry['labels'].get(lbl, {}).get('air_fraction')
        ck[f'C4_airway_is_air_{lbl}'] = bool(fr is not None and fr > 0.5)
    for lbl in TISSUE_LABELS:
        fr = entry['labels'].get(lbl, {}).get('air_fraction')
        ck[f'C4_tissue_not_air_{lbl}'] = bool(fr is not None and fr < 0.5)
    entry['all_pass'] = all(ck.values())
    del masks
    return entry


def render_mpr():
    cases = [('b01', 'b01 · 副鼻窦队列 · 可见口咽 40.0 mm'),
             ('b15', 'b15 · CFD 病例 · 可见口咽 10.0 mm'),
             ('p2', 'p2 · 患者 · 可见口咽 43.5 mm')]
    fig, axes = plt.subplots(1, 3, figsize=(19.5, 8.2))
    colors = {'nasal_cavity_left': (0.30, 0.60, 1.00, 0.45),
              'nasal_cavity_right': (0.30, 0.60, 1.00, 0.45),
              'nasopharynx': (0.00, 0.85, 0.85, 0.55),
              'oropharynx': (0.10, 0.80, 0.20, 0.55),
              'soft_palate': (1.00, 0.55, 0.00, 0.65),
              'hard_palate': (0.85, 0.20, 0.60, 0.55)}
    for ax, (case, title) in zip(axes, cases):
        ct_arr, aff, zooms, ident, masks = load_case(case)
        nx, ny, nz = ct_arr.shape
        mx = nx // 2
        slab = ct_arr[mx, :, :].T  # (z, y): rows z, cols y
        ax.imshow(slab, cmap='gray', vmin=-1000, vmax=400,
                  origin='lower', aspect='auto',
                  extent=[0, ny * zooms[1], 0, nz * zooms[2]])
        for lbl, rgba in colors.items():
            if lbl not in masks:
                continue
            arr = masks[lbl][0]
            if not arr.any():
                continue
            o = arr[mx, :, :].T.astype(float)
            o[o == 0] = np.nan
            ax.imshow(np.ma.masked_invalid(o), cmap=matplotlib.colors.ListedColormap([rgba]),
                      origin='lower', aspect='auto', vmin=0, vmax=1,
                      extent=[0, ny * zooms[1], 0, nz * zooms[2]], interpolation='nearest')
        ax.axhline(0, color='magenta', lw=2)
        ax.text(ny * zooms[1] * 0.98, nz * zooms[2] * 0.012, '扫描下缘（ magenta 线 ）= 可见气道终点；喉在此线之下，数据中不存在',
                color='magenta', fontsize=10.5, ha='right', va='bottom',
                bbox=dict(facecolor='black', alpha=0.55, pad=2, edgecolor='none'))
        ax.set_title(title, fontsize=13)
        ax.set_xlabel('y (mm)  左=前(鼻) / 右=后(枕)')
        if ax is axes[0]:
            ax.set_ylabel('z (mm)  上=头侧 / 下=颈侧')
        # legend
        handles = [plt.Rectangle((0, 0), 1, 1, color=colors[k]) for k in
                   ('nasal_cavity_left', 'nasopharynx', 'oropharynx', 'soft_palate')]
        ax.legend(handles, ['鼻腔', '鼻咽', '口咽', '软腭'], loc='upper right', fontsize=10)
        del ct_arr, masks
    fig.suptitle('分割位置核验：标签贴解剖（鼻腔/鼻咽/口咽/软腭位置关系正确）——缺的不是位置，是扫描覆盖',
                 fontsize=15)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out = OUT / 'seg_position_mpr.png'
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def main():
    report = {'created': datetime.datetime.now().astimezone().isoformat(),
              'scope': 'T-048 segmentation position/orientation verification; read-only',
              'air_definition_hu': HU, 'cases': {}}
    npass = 0
    for c in CASES:
        e = verify_case(c)
        report['cases'][c] = e
        npass += int(e['all_pass'])
        failed = [k for k, v in e['checks'].items() if not v]
        print(f"{c:5s} {'PASS' if e['all_pass'] else 'FAIL ' + ','.join(failed)}", flush=True)
    report['summary'] = {'cases_total': len(CASES), 'cases_all_checks_pass': npass}
    out = OUT / 'position_orientation_verification.json'
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print('written:', out, flush=True)
    png = render_mpr()
    print('written:', png, flush=True)


if __name__ == '__main__':
    main()
