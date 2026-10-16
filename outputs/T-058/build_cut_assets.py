"""Build the T-058 anatomical-cut 3D assets on the ESTABLISHED viewer stack.

The project already has a pinned, offline 3D rendering method:
work/07_cfd_pipeline/viewer/vendor/ (three 0.180.0 + OrbitControls, sha-pinned
in source.json), consumed by viewer/index.html and workspace/upper-airway.html
via an import map over the 8769 workspace server. This builder produces the
same kind of assets for the three T-058 cut cases and a purpose-built page in
the same place, instead of a private viewer:

  work/07_cfd_pipeline/workspace/t058_cut_data.json   index (schema, honesty)
  work/07_cfd_pipeline/workspace/t058_<case>.json     per-case mesh payloads

Payload per case (LPS mm, display geometry only, cfd_ready false):
  patches.wall / nostril_L / nostril_R / oropharynx_truncation_outlet
  ghost      source faces entirely below the tilted plane (what the oblique
             cut removed that the retired axial cut kept on the low side)
  axis       fitted airway axis segment (anchor -10 mm .. +22 mm)
  plane_new  the anatomical (perpendicular) cut plane loop
  plane_axial the retired axial plane loop, for reference
  meta       the numbers shown in the side panel

Decimation uses the project's own decimate_for_viewer (vtkDecimatePro,
preserve topology) with the same 40k-face budget convention as
export_candidate_preview. Coordinates rounded to 4 decimals (0.1 um), the
same read-back verification style as export_candidate_preview.
"""
import base64
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import vtk
from vtk.util import numpy_support

sys.path.insert(0, str(Path('D:/项目/鼻腔建模/work/lib')))
from export_candidate_preview import triangle_arrays, decimate_for_viewer
from auto_opening_pipeline import truncation_plane

CASES = ('b01', 'b02', 'b15')
SURF = Path('C:/ts_work/t058_oroext_surfaces')
OPEN_ANAT = Path('C:/ts_work/t058_oroext_opening_anat')
OPEN_AXIAL = Path('C:/ts_work/t058_oroext_opening')     # retired axial-cut run
OUT_DIR = Path('D:/项目/鼻腔建模/work/07_cfd_pipeline/workspace')
WALL_FACES = 25000
GHOST_FACES = 8000
ROUND = 4
LABELS = {'b01': 'b01 · 解剖斜切', 'b02': 'b02 · 解剖斜切', 'b15': 'b15 · 解剖斜切'}


def poly_of(points, tris):
    poly = vtk.vtkPolyData()
    pts = vtk.vtkPoints()
    pts.SetData(numpy_support.numpy_to_vtk(np.ascontiguousarray(points, dtype=np.float64),
                                           deep=True))
    poly.SetPoints(pts)
    ca = vtk.vtkCellArray()
    conn = np.ascontiguousarray(tris.reshape(-1), dtype=np.int64)
    offs = np.arange(0, 3 * (len(tris) + 1), 3, dtype=np.int64)
    ca.SetData(numpy_support.numpy_to_vtk(offs, deep=True),
               numpy_support.numpy_to_vtk(conn, deep=True))
    poly.SetPolys(ca)
    return poly


def mesh_payload(points, tris, max_faces):
    """Established-style payload: shared vertex pool + flat index array.

    Same layout as export_candidate_preview's viewer_mesh.json (vertices as
    flat xyz triplets, indices as flat zero-based triplets), so the page code
    and the decimation budget behave like the established viewer's. Vertices
    are welded on the rounded value; read-back is verified.
    """
    if len(tris) > max_faces:
        pts, tri = triangle_arrays(decimate_for_viewer(poly_of(points, tris), max_faces))
    else:
        pts, tri = points, tris
    v = np.round(np.asarray(pts, dtype=np.float64), ROUND).reshape(-1, 3)
    # weld on the rounded coordinates: exact float keys are unstable across
    # the decimator's arithmetic
    pool, remap = {}, np.empty(len(v), dtype=np.int64)
    for i, key in enumerate(map(tuple, v)):
        j = pool.get(key)
        if j is None:
            j = len(pool)
            pool[key] = j
        remap[i] = j
    tri_idx = remap[np.asarray(tri, dtype=np.int64).reshape(-1)]
    used = np.unique(tri_idx)
    compact = np.zeros(len(pool), dtype=np.int64)
    compact[used] = np.arange(len(used))
    verts = np.array([None] * len(pool), dtype=object)
    for key, j in pool.items():
        verts[j] = key
    verts = np.asarray([verts[j] for j in used], dtype=np.float64)
    tri_idx = compact[tri_idx]
    return {'vertices': verts.ravel().tolist(), 'indices': tri_idx.tolist(),
            'triangles': int(len(tri)),
            'bounds_lps_mm': {'min': verts.min(0).tolist(),
                              'max': verts.max(0).tolist()}}


def loop_payload(points):
    return np.round(np.asarray(points, dtype=np.float64), ROUND).reshape(-1, 3).ravel().tolist()


def build_case(case):
    r = vtk.vtkXMLPolyDataReader()
    r.SetFileName(str(OPEN_ANAT / case / 'auto_placed.vtp'))
    r.Update()
    cut_p, cut_t = triangle_arrays(r.GetOutput())
    patches = [r.GetOutput().GetCellData().GetAbstractArray('boundary_patch').GetValue(i)
               for i in range(r.GetOutput().GetNumberOfCells())]
    r2 = vtk.vtkXMLPolyDataReader()
    r2.SetFileName(str(SURF / case / 'source_surface.vtp'))
    r2.Update()
    src_p, src_t = triangle_arrays(r2.GetOutput())
    plane, info = truncation_plane(SURF / case)
    o = np.asarray(plane['point_lps_mm'], float)
    n = np.asarray(plane['normal_lps'], float)

    out = {'case': case, 'schema': 't058_cut_mesh/v1',
           'status': 'unreviewed_candidate_preview', 'display_geometry_only': True,
           'review_required': True, 'cfd_ready': False,
           'coordinate_system': 'LPS', 'unit': 'mm'}
    patch_payloads = {}
    for name in ('nostril_L', 'nostril_R', 'oropharynx_truncation_outlet'):
        sel = np.asarray([p == name for p in patches])
        patch_payloads[name] = mesh_payload(cut_p, cut_t[sel], GHOST_FACES)
    wall_sel = ~np.asarray([p in ('nostril_L', 'nostril_R',
                                  'oropharynx_truncation_outlet') for p in patches])
    patch_payloads['wall'] = mesh_payload(cut_p, cut_t[wall_sel], WALL_FACES)
    out['patches'] = patch_payloads

    s = (src_p - o) @ n
    ghost = np.all(s[src_t] < 0, axis=1)
    out['ghost'] = mesh_payload(src_p, src_t[ghost], GHOST_FACES)

    a = n / np.linalg.norm(n)
    out['axis'] = loop_payload([o - 10.0 * a, o, o + 22.0 * a])
    ref = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(n, ref)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    half = 22.0
    corners = [o + sx * half * u + sy * half * v
               for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1), (-1, -1))]
    out['plane_new'] = loop_payload(corners)
    out['plane_axial'] = loop_payload(
        [[o[0] + sx * half, o[1] + sy * half, info['z_cut_lowest_mm']]
         for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1), (-1, -1))])

    rep_a = json.load(open(OPEN_ANAT / f'{case}.json', encoding='utf-8'))
    rep_x = json.load(open(OPEN_AXIAL / f'{case}.json', encoding='utf-8'))
    af = rep_a['truncation_outlet']['axis_fit']
    out['meta'] = {
        'decision': rep_a['decision'],
        'nostril_L': rep_a['patch_areas_mm2']['nostril_L'],
        'nostril_R': rep_a['patch_areas_mm2']['nostril_R'],
        'outlet': rep_a['patch_areas_mm2']['oropharynx_truncation_outlet'],
        'outlet_axial': rep_x['patch_areas_mm2']['oropharynx_truncation_outlet'],
        'tilt_deg': af['tilt_deg'],
        'drift_xy_mm': af['drift_xy_mm'],
        'fit_height_mm': af['height_mm'],
        'z_anchor_mm': rep_a['truncation_outlet']['z_anchor_mm'],
        'z_bottom_mm': rep_a['truncation_outlet']['z_bottom_center_mm'],
        'volume_mm3': round(rep_a['surface_qc']['signed_volume_mm3'], 1),
        'removed_mm3': rep_a['volume_removed_mm3'],
    }
    out['source'] = {
        'cut_surface': str((OPEN_ANAT / case / 'auto_placed.vtp').as_posix()),
        'cut_surface_sha256': hashlib.sha256(
            (OPEN_ANAT / case / 'auto_placed.vtp').read_bytes()).hexdigest(),
        'report': str((OPEN_ANAT / f'{case}.json').as_posix()),
        'report_sha256': hashlib.sha256(
            (OPEN_ANAT / f'{case}.json').read_bytes()).hexdigest(),
        'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
    }
    return out


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = []
    for case in CASES:
        payload = build_case(case)
        path = OUT_DIR / f't058_{case}.json'
        path.write_text(json.dumps(payload, ensure_ascii=False,
                                   separators=(',', ':'), allow_nan=False),
                        encoding='utf-8')
        cases.append({'id': case, 'label': LABELS[case], 'type': 'patient_preview',
                      'mesh_url': f'./t058_{case}.json',
                      'note': 'T-058 解剖斜切（出口垂直气道轴）几何检视；非 CFD 结果。',
                      'meta': payload['meta']})
        print(f'{case}: wall {payload["patches"]["wall"]["triangles"]} tris, '
              f'ghost {payload["ghost"]["triangles"]} tris, '
              f'{path.stat().st_size/1e6:.2f} MB')
    index = {
        'schema': 't058_cut_viewer/v1',
        'title': 'T-058 切割结果三维检视 · 解剖斜切',
        'coordinate_system': 'LPS', 'unit': 'mm',
        'display_geometry_only': True, 'cfd_ready': False,
        'patient_cfd_results': 0,
        'clinical_status': 'generalisation_test_only_no_human_review',
        'cut_rule': 'outlet perpendicular to the fitted local airway axis; lowest '
                    'point 0.5 mm above the bottom voxel centre (same anchor rule '
                    'as the retired axial cut)',
        'cases': cases,
    }
    (OUT_DIR / 't058_cut_data.json').write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding='utf-8')
    print('index:', OUT_DIR / 't058_cut_data.json')


if __name__ == '__main__':
    main()
