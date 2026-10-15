"""Measure the real nostril aperture geometry on b15 (auto_placed.vtp).

For each nostril patch: fit a plane (SVD), report the outward normal and the
in-plane principal axes with their lengths and directions. LPS coords:
+x=left, +y=posterior, +z=superior.
"""
import json

import numpy as np
import vtk

VTP = 'C:/ts_work/t058_oroext_opening/b15/auto_placed.vtp'
AREA = {'nostril_L': 80.03741, 'nostril_R': 80.057289}

r = vtk.vtkXMLPolyDataReader()
r.SetFileName(VTP)
r.Update()
pd = r.GetOutput()
patch = pd.GetCellData().GetAbstractArray('boundary_patch')
if patch is None:
    raise SystemExit('boundary_patch array not found')

patches = {}
for i in range(pd.GetNumberOfCells()):
    name = patch.GetValue(i)
    cell = pd.GetCell(i)
    pts = cell.GetPoints()
    if pts is None:
        continue
    n = pts.GetNumberOfPoints()
    ids = cell.GetPointIds()
    for j in range(n):
        patches.setdefault(name, set()).add(ids.GetId(j))

print('patch names:', sorted(patches))


def axis_text(v):
    """Describe a unit vector in clinical terms (LPS)."""
    x, y, z = v
    parts = []
    if abs(x) > 0.05:
        parts.append(('左' if x > 0 else '右') + f' {abs(x):.2f}')
    if abs(y) > 0.05:
        parts.append(('后' if y > 0 else '前') + f' {abs(y):.2f}')
    if abs(z) > 0.05:
        parts.append(('上' if z > 0 else '下') + f' {abs(z):.2f}')
    return ' '.join(parts)


for name in ('nostril_L', 'nostril_R'):
    pts = np.array([pd.GetPoint(i) for i in sorted(patches[name])])
    c = pts.mean(axis=0)
    u, s, vt = np.linalg.svd(pts - c, full_matrices=False)
    n = vt[2]
    if n[2] > 0:            # make the normal point outward (down/front)
        n = -n
    a1, a2 = vt[0], vt[1]
    # in-plane extent along each principal axis
    proj1 = (pts - c) @ a1
    proj2 = (pts - c) @ a2
    len1 = proj1.max() - proj1.min()
    len2 = proj2.max() - proj2.min()
    # equivalent-diameter circle with the measured cap area, for reference
    d_eq = 2 * np.sqrt(AREA[name] / np.pi)
    tilt_from_horizontal = np.degrees(np.arccos(abs(n[2])))
    sag = np.array([n[1], n[2]])
    sag /= np.linalg.norm(sag)
    ang = np.degrees(np.arctan2(sag[0], -sag[1]))  # deg forward of straight-down
    print(f'\n== {name} ==  rim points: {len(pts)}')
    print(f'  centroid          : ({c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f}) mm')
    print(f'  outward normal    : ({n[0]:+.3f}, {n[1]:+.3f}, {n[2]:+.3f})'
          f'  = {axis_text(n)}')
    print(f'  plane tilt        : {tilt_from_horizontal:.1f} deg from horizontal;'
          f' faces {ang:.1f} deg forward of straight-down (sagittal)')
    print(f'  in-plane axes     : major {len1:.1f} mm {axis_text(a1)}')
    print(f'                      minor {len2:.1f} mm {axis_text(a2)}')
    print(f'  aspect major/minor: {len1 / len2:.2f}')
    print(f'  cap area {AREA[name]:.2f} mm2 -> equivalent diameter'
          f' {d_eq:.1f} mm')
    # vertical vs horizontal long axis, in patient (z = up-down) terms
    long_axis = a1 if len1 >= len2 else a2
    print(f'  long axis vertical share: {abs(long_axis[2]):.2f}'
          f' (1.0 = perfectly up-down, 0.0 = left-right)')
