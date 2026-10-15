"""Read-only, frozen T026 engineering candidates for the local workbench.

This module never imports the patient manager or changes CFD admission. Display
surfaces are extracted offline once, with no padding, smoothing or hole filling.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'outputs/T-026/runs/20261015_04_full'
BUNDLE = ROOT / 'outputs/T-030/assets-v1'
CASES = ('p0', 'p1', 'p2', 'p3', 'p3t1')
SOURCE_HASHES = {
    'p0_audit.json': '625f5e640bf9c27defb8068a754d57bad5f4c164c1e3143c3274b7e33c0381f1',
    'p1_audit.json': 'a67573db12680ba7a3e5776520485806485d92ce8df54695f61bb24f8f4760cc',
    'p2_audit.json': 'f882b1f9193ab7a23cd4441cf335e5b39c9c8e45ee67058118182c398f766ec4',
    'p3_audit.json': '281e241670cedfc70a2c8f25e8012969c93c483f1ce7006d75b2aee6feb7aeda',
    'p3t1_audit.json': '5fe8b0ba2e3ec76c09300280b4081e911ae6769fcb4d40f4e808a2f131e2f60b',
    'p3_candidate_report.json': '94346376b2fbe5041ab4475289a991f634d849e3d2a819d335be15abea83e43d',
    'p3_nasal_original_candidate.nii.gz': 'c4b18d31fb55981d2d46e2695cc36b4a2e47a38cadf19286ecfd4c08bf8eff72',
    'p3_nasal_oropharynx_candidate.nii.gz': '9e34656cd8cdc15fb06d2425d647940dba0bdf9761ebe27baeffac80282d6b52',
    'p3_original_vs_oropharynx.png': 'd254c92256351f7de1c6c4b28c4bedb2f531654d56165512543b1cb7cfef9886',
}
# Set only after the deterministic local export has actually run.
BUNDLE_MANIFEST_SHA256 = 'e53c905cc98aafa6777cfa85fd2fc441229e2ca07cfd40db381c6b35cd871dd5'
ASSET_NAMES = frozenset({'baseline.vertices.bin', 'baseline.triangles.bin',
                         'added.vertices.bin', 'added.triangles.bin', 'ct-comparison.png'})


def verified_bytes(path: Path, digest: str) -> bytes:
    if not path.is_file():
        raise FileNotFoundError('咽部扩展资产缺失，未加载其他病例')
    value = path.read_bytes()
    if sha256(value).hexdigest() != digest:
        raise ValueError('咽部扩展资产指纹变化，已拒绝显示；请复核来源')
    return value


def checked_source(source=SOURCE):
    result = {}
    for name, digest in SOURCE_HASHES.items():
        value = verified_bytes(source / name, digest)
        if name.endswith('.json'):
            result[name] = json.loads(value)
    for case in CASES:
        audit = result[f'{case}_audit.json']
        if audit['case'] != case or audit['patient_B_mapping'] != 'unknown':
            raise ValueError('工程扫描身份或症状映射不符合冻结输入')
    report = result['p3_candidate_report.json']
    if report['case'] != 'p3' or report['CFD_admitted'] or report['outlet_selected']:
        raise ValueError('候选身份或只读工程状态不符合冻结输入')
    return result


def surface_from_mask(mask_zyx, spacing_xyz, origin_lps, direction):
    """0.5 isosurface, preserving all components, no zero padding at CT faces.

    Cropping includes one existing background voxel where available. It never
    adds a voxel beyond the scanned image. Consequently a CT-face intersection
    remains open instead of becoming a fabricated end cap.
    """
    import numpy as np
    import vtk
    from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy

    occupied = np.argwhere(mask_zyx)
    if not len(occupied):
        raise ValueError('空掩膜没有可显示的表面')
    low = np.maximum(occupied.min(axis=0) - 1, 0)
    high = np.minimum(occupied.max(axis=0) + 2, mask_zyx.shape)
    crop = np.ascontiguousarray(mask_zyx[tuple(slice(a, b) for a, b in zip(low, high))], dtype=np.uint8)
    image = vtk.vtkImageData()
    image.SetDimensions(*crop.shape[::-1])
    image.GetPointData().SetScalars(numpy_to_vtk(crop.ravel(), deep=True))
    contour = vtk.vtkFlyingEdges3D()
    contour.SetInputData(image)
    contour.SetValue(0, .5)
    contour.ComputeNormalsOff()
    contour.Update()
    poly = contour.GetOutput()
    index_xyz = vtk_to_numpy(poly.GetPoints().GetData()).astype(np.float64) + low[::-1]
    points = np.asarray(origin_lps) + (index_xyz * np.asarray(spacing_xyz)) @ np.asarray(direction).reshape(3, 3).T
    cells = poly.GetPolys()
    offsets = vtk_to_numpy(cells.GetOffsetsArray())
    if not np.all(np.diff(offsets) == 3):
        raise ValueError('显示面不是三角形')
    faces = vtk_to_numpy(cells.GetConnectivityArray()).reshape(-1, 3).astype('<u4')
    vertices = points.astype('<f4')
    edges = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return vertices, faces, {
        'vertices': len(points), 'triangles': len(faces),
        'bounds_LPS_mm': [points.min(axis=0).tolist(), points.max(axis=0).tolist()],
        'float32_max_abs_error_mm': float(np.abs(vertices.astype(float) - points).max()),
        'open_boundary_edges': int(np.sum(counts == 1)),
        'source_voxels': int(mask_zyx.sum()),
        'extraction': 'vtkFlyingEdges3D binary isovalue 0.5; original-grid coordinates; no padding/smoothing/closing/component filtering',
    }


def build_bundle(out=BUNDLE):
    import numpy as np
    import SimpleITK as sitk
    import vtk

    checked_source()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    # This Windows SimpleITK build cannot open a Unicode absolute NIfTI path.
    # Offline build only: chdir to the verified source, read ASCII basenames,
    # then restore before any output. No process cwd mutation in HTTP requests.
    import os
    previous = Path.cwd()
    try:
        os.chdir(SOURCE)
        baseline_img = sitk.ReadImage('p3_nasal_original_candidate.nii.gz')
        extended_img = sitk.ReadImage('p3_nasal_oropharynx_candidate.nii.gz')
    finally:
        os.chdir(previous)
    geometry = lambda im: (im.GetSize(), im.GetSpacing(), im.GetOrigin(), im.GetDirection())
    if geometry(baseline_img) != geometry(extended_img):
        raise ValueError('候选网格不一致')
    base = sitk.GetArrayFromImage(baseline_img) > 0
    extended = sitk.GetArrayFromImage(extended_img) > 0
    if np.any(base & ~extended) or int(base.sum()) != 397783 or int(extended.sum()) != 445592:
        raise ValueError('原域保留或已知体素数不一致')
    manifest = {
        'schema': 'nasal-cfd/upper-airway-display/v1', 'case': 'p3', 'coordinate_system': 'LPS', 'unit': 'mm',
        'patient_symptom_mapping': 'unknown', 'clinical_review': 'not_reviewed',
        'outlet_selected': False, 'CFD_admitted': False, 'read_only': True,
        'source_run': 'T-026/20261015_04_full', 'source_sha256': SOURCE_HASHES,
        'CT': {'size_xyz': list(baseline_img.GetSize()), 'spacing_xyz_mm': list(baseline_img.GetSpacing()),
               'origin_LPS_mm': list(baseline_img.GetOrigin()), 'direction_row_major': list(baseline_img.GetDirection())},
        'display_version': vtk.vtkVersion.GetVTKVersion(), 'assets': {}, 'surfaces': {},
    }
    for name, mask in [('baseline', base), ('added', extended & ~base)]:
        vertices, faces, facts = surface_from_mask(mask, baseline_img.GetSpacing(), baseline_img.GetOrigin(), baseline_img.GetDirection())
        for suffix, array in [('vertices', vertices), ('triangles', faces)]:
            filename = f'{name}.{suffix}.bin'
            value = array.tobytes()
            (out / filename).write_bytes(value)
            manifest['assets'][filename] = {'sha256': sha256(value).hexdigest(), 'bytes': len(value),
                                           'dtype': 'float32_le' if suffix == 'vertices' else 'uint32_le'}
        manifest['surfaces'][name] = facts
    png = verified_bytes(SOURCE / 'p3_original_vs_oropharynx.png', SOURCE_HASHES['p3_original_vs_oropharynx.png'])
    (out / 'ct-comparison.png').write_bytes(png)
    manifest['assets']['ct-comparison.png'] = {'sha256': sha256(png).hexdigest(), 'bytes': len(png)}
    value = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    (out / 'manifest.json').write_bytes(value)
    checked_source()  # Ensure input bytes have not changed during extraction.
    return {'manifest_sha256': sha256(value).hexdigest(), 'surfaces': manifest['surfaces'], 'assets': manifest['assets']}


class UpperAirwayWorkspace:
    def __init__(self, source=SOURCE, bundle=BUNDLE):
        self.source, self.bundle = Path(source), Path(bundle)

    def catalog(self):
        source = checked_source(self.source)
        cases = [self._case(case, source) for case in CASES]
        return {'schema': 'nasal-cfd/upper-airway-catalog/v1', 'read_only': True, 'cases': cases}

    def _case(self, case, source):
        audit = source[f'{case}_audit.json']
        labels = audit['labels']
        return {
            'case': case, 'kind': 'existing_engineering_scan', 'patient_symptom_mapping': 'unknown',
            'candidate_status': 'available' if case == 'p3' else 'not_generated',
            'clinical_review': 'not_reviewed', 'outlet_selected': False, 'CFD_admitted': False,
            'inferior_face_air_voxels': labels['oropharynx']['air_HU_lt_minus300']['boundary_contact']['face_voxel_counts']['z_low'],
            'hypopharynx_empty': labels['hypopharynx']['semantic']['empty'],
            'larynx_air_exists': labels['larynx_air']['exists'], 'CT': audit['CT'],
            'audit_sha256': SOURCE_HASHES[f'{case}_audit.json'],
        }

    def case(self, case):
        if case not in CASES:
            raise FileNotFoundError('该病例没有冻结的咽部扩展候选；未加载默认病例')
        source = checked_source(self.source)
        result = self._case(case, source)
        if case == 'p3':
            manifest = json.loads(verified_bytes(self.bundle / 'manifest.json', BUNDLE_MANIFEST_SHA256))
            if manifest['case'] != case or manifest['CFD_admitted'] or set(manifest['assets']) != ASSET_NAMES:
                raise ValueError('显示资产身份或范围校验失败')
            # Eagerly reject missing/changed assets before claiming an available view.
            for name, asset in manifest['assets'].items():
                verified_bytes(self.bundle / name, asset['sha256'])
            result['candidate'] = manifest
        return result

    def asset_bytes(self, case, name):
        if case != 'p3' or name not in ASSET_NAMES:
            raise FileNotFoundError('显示资产不在只读允许清单中')
        data = self.case(case)
        return verified_bytes(self.bundle / name, data['candidate']['assets'][name]['sha256'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--out', type=Path, default=BUNDLE)
    args = parser.parse_args()
    if not args.build:
        parser.error('only offline --build is supported; HTTP API is read-only')
    print(json.dumps(build_bundle(args.out), ensure_ascii=False, indent=2))
