"""Per-slice airway profile above the truncation cut, for the three cases.

Prints, per case: slice index, z (LPS mm), largest-component area (mm2),
centroid (x, y) - from the cut upward until the airway ends. Used to choose
the axis-fit window for the anatomical (perpendicular-to-airway) cut: the
window must stay inside the tube and stop where the nasopharyngeal cavity
starts (the section growing well past the tube's cross-section).
"""
import sys
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from scipy import ndimage

CASES = ('b01', 'b02', 'b15')
SURF = Path('C:/ts_work/t058_oroext_surfaces')
CUT_ABOVE = 0.5


def main():
    for case in CASES:
        p = SURF / case / 'air_mask.nii.gz'
        m = sitk.ReadImage(str(p))
        arr = sitk.GetArrayFromImage(m)          # (z, y, x)
        sp, org = m.GetSpacing(), m.GetOrigin()
        zs = org[2] + np.arange(arr.shape[0]) * sp[2]
        z_cut = org[2] + CUT_ABOVE
        i_cut = int(np.argmin(np.abs(zs - z_cut)))
        print(f'\n================ {case} ================')
        print(f'  shape {arr.shape} spacing {tuple(round(s, 3) for s in sp)} '
              f'z_bot {org[2]:.2f} z_cut {z_cut:.2f} i_cut {i_cut}')
        a_cut = None
        for i in range(i_cut, arr.shape[0]):
            sl = arr[i] > 0
            if not sl.any():
                print(f'  airway ends at slice {i} (z {zs[i]:.2f})')
                break
            lab, n = ndimage.label(sl)
            if n > 1:
                sl = lab == (np.argmax(np.bincount(lab.ravel())[1:]) + 1)
            yy, xx = np.where(sl)
            a = len(xx) * sp[0] * sp[1]
            cx = org[0] + xx.mean() * sp[0]
            cy = org[1] + yy.mean() * sp[1]
            if i == i_cut:
                a_cut = a
            dz = zs[i] - z_cut
            print(f'  i={i:3d} dz={dz:6.2f} area={a:8.2f} '
                  f'({a / a_cut:5.2f}x cut)  cx={cx:8.2f} cy={cy:8.2f}')


if __name__ == '__main__':
    main()
