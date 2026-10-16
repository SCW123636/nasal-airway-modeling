"""Is the oropharynx truncation cut in the right place, facing the right way?

Measures, per case (b01/b02/b15), from the production air mask and the
TotalSegmentator ROI labels:

  position  - where the cut sits relative to every anatomical landmark that
              exists in the data (soft palate tip, nasopharynx bottom,
              hypopharynx stub, scan inferior face), and how much open airway
              lies below the velopharyngeal port (the margin that decouples
              the artificial p=0 exit from the nasal flow field)
  direction - the local airway axis in the bottom 12 mm of the domain, the
              obliquity of the axial cut against it, and the ellipticity the
              obliquity imposes on the outlet cap
  regime    - exit velocity and Reynolds number at the truncation, to confirm
              the cut does not push the laminar pipeline out of its regime

LPS coords: +x left, +y posterior, +z superior. Bottom of the scan = min z.
"""
import json
import sys
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from scipy import ndimage

CASES = ('b01', 'b02', 'b15')
SURF = Path('C:/ts_work/t058_oroext_surfaces')
MASKS = Path('C:/ts_work')
OPENING = Path('C:/ts_work/t058_oroext_opening')
NU = 1.5e-5          # kinematic viscosity of air at ~32 C, m^2/s
Q_TOTAL = 2.5e-4     # m^3/s (125 mL/s per nostril)

LABELS = ('nasal_cavity_left', 'nasal_cavity_right', 'nasopharynx',
          'oropharynx', 'soft_palate', 'hard_palate', 'hypopharynx')


def load(p):
    m = sitk.ReadImage(str(p))
    return sitk.GetArrayFromImage(m), m.GetSpacing(), m.GetOrigin()  # (z,y,x)


def label_extent(arr, sp, org):
    """(zmin_mm, zmax_mm, nvox) of a binary label, LPS mm."""
    zz = np.where(arr.any(axis=(1, 2)))[0]
    if len(zz) == 0:
        return None
    return (org[2] + zz.min() * sp[2], org[2] + zz.max() * sp[2], int(arr.sum()))


def main():
    for case in CASES:
        print(f'\n================ {case} ================')
        rep = json.load(open(OPENING / f'{case}.json', encoding='utf-8'))
        tp = rep['truncation_outlet']
        area_out = rep['patch_areas_mm2']['oropharynx_truncation_outlet']
        z_cut = tp['z_cut_mm']
        z_bot = tp['z_bottom_center_mm']
        print(f'  cut plane z = {z_cut:.3f} mm (bottom voxel centre {z_bot:.3f}, '
              f'+0.5 mm), outlet cap {area_out:.2f} mm2, '
              f'{tp["bottom_air_voxels"]} air voxels on the bottom slice')

        air, sp_a, org_a = load(SURF / case / 'air_mask.nii.gz')
        print(f'  air mask: shape {air.shape}, spacing {tuple(round(s, 3) for s in sp_a)}')

        # ---- label extents (geometry cross-check against the air mask) ----
        ext = {}
        for name in LABELS:
            p = MASKS / case / 'masks' / f'{name}.nii.gz'
            if not p.is_file():
                continue
            arr, sp, org = load(p)
            if arr.shape != air.shape:
                print(f'  !! {name}: shape {arr.shape} != air mask {air.shape}')
                continue
            ext[name] = label_extent(arr, sp, org)
        for name in LABELS:
            if name in ext and ext[name]:
                z0, z1, n = ext[name]
                print(f'  {name:22s} z [{z0:8.2f}, {z1:8.2f}]  len {z1 - z0:6.2f} mm  '
                      f'{n:7d} vox')

        # ---- airway profile + bottom-region geometry ----
        zs = org_a[2] + np.arange(air.shape[0]) * sp_a[2]
        area_prof = air.sum(axis=(1, 2)) * sp_a[0] * sp_a[1]     # mm2 per slice
        # largest component per slice, for centroid/axis work near the bottom
        i_cut = int(np.argmin(np.abs(zs - z_cut)))
        i0 = max(0, i_cut - int(round(16.0 / sp_a[2])))
        cents, areas, zs_loc = [], [], []
        for i in range(i0, min(air.shape[0], i_cut + 2)):
            sl = air[i] > 0
            if not sl.any():
                continue
            lab, n = ndimage.label(sl)
            if n > 1:
                sl = lab == (np.argmax(np.bincount(lab.ravel())[1:]) + 1)
            yy, xx = np.where(sl)
            a = len(xx) * sp_a[0] * sp_a[1]
            cents.append([org_a[0] + xx.mean() * sp_a[0],
                          org_a[1] + yy.mean() * sp_a[1]])
            areas.append(a)
            zs_loc.append(zs[i])
        cents, areas, zs_loc = map(np.array, (cents, areas, zs_loc))

        # local axis: centroid trajectory over the bottom 12 mm
        m = (zs_loc >= zs_loc[-1] - 12.0)
        A = np.vstack([zs_loc[m], np.ones(m.sum())]).T
        cx = np.linalg.lstsq(A, cents[m, 0], rcond=None)[0]
        cy = np.linalg.lstsq(A, cents[m, 1], rcond=None)[0]
        axis = np.array([cx[0], cy[0], 1.0])
        axis /= np.linalg.norm(axis)
        incl = np.degrees(np.arccos(abs(axis[2])))          # from vertical
        ap = 'posterior' if axis[1] > 0 else 'anterior'     # drift going down
        obl = np.degrees(np.arccos(abs(axis[2])))           # cut normal is +z
        print(f'  bottom-16mm profile: area {areas.min():.1f}-{areas.max():.1f} mm2, '
              f'centroid drift x {np.ptp(cents[m, 0]):.2f} / '
              f'y {np.ptp(cents[m, 1]):.2f} mm')
        print(f'  local tube axis    : {incl:.1f} deg off vertical, drifting '
              f'{ap} going down; axial-cut obliquity {obl:.1f} deg')
        # ellipticity imposed on the cap by the obliquity
        print(f'  cap area inflation vs true cross-section: '
              f'x{1.0 / max(np.cos(np.radians(obl)), 1e-9):.3f} '
              f'(ellipse minor/major = cos {obl:.1f} deg = '
              f'{np.cos(np.radians(obl)):.3f})')

        # ---- position margins (z decreases downward; distance = station - cut) ----
        d = {}
        if 'soft_palate' in ext and ext['soft_palate']:
            # inferior tip of the velum = zmin of the label
            d['airway below velum tip'] = ext['soft_palate'][0] - z_cut
            d['velum tip FOV-truncated'] = ext['soft_palate'][0] <= z_bot + 1e-6
        if 'nasopharynx' in ext and ext['nasopharynx']:
            d['airway below nasopharynx floor'] = ext['nasopharynx'][0] - z_cut
        if 'oropharynx' in ext and ext['oropharynx']:
            d['oropharynx label length'] = ext['oropharynx'][1] - ext['oropharynx'][0]
            d['oropharynx label bottom - cut'] = ext['oropharynx'][0] - z_cut
        if 'hypopharynx' in ext and ext['hypopharynx']:
            # superior end of the hypopharynx label = zmax; positive means the
            # cut sits at/below it, i.e. the exit plane is already in hypopharynx
            d['hypopharynx top vs cut'] = ext['hypopharynx'][1] - z_cut
            d['hypopharynx voxels'] = ext['hypopharynx'][2]
        for k, v in d.items():
            if 'voxels' in k or 'truncated' in k:
                print(f'  {k:34s}: {v!s:>10s}')
            else:
                print(f'  {k:34s}: {v:9.2f} mm')

        # narrowing check near the exit
        w = areas[-int(round(20.0 / sp_a[2])):]
        i_min = int(np.argmin(w))
        print(f'  min area in bottom 20 mm: {w.min():.1f} mm2 at '
              f'{zs_loc[-1] - (len(w) - 1 - i_min) * sp_a[2]:.2f} mm '
              f'({"at the cut" if i_min >= len(w) - 2 else "above the cut"})')

        # ---- exit regime ----
        u = Q_TOTAL / (area_out * 1e-6)
        d_eq = 2 * np.sqrt(area_out / np.pi) * 1e-3
        print(f'  exit: u_mean {u:.2f} m/s, d_eq {d_eq * 1e3:.1f} mm, '
              f'Re {u * d_eq / NU:.0f} (laminar threshold ~2300)')


if __name__ == '__main__':
    main()
