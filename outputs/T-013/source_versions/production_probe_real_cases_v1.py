"""Isolated T-013 evidence. Calls production clipper, never copies its algorithm.

DynamicSelector is an exploratory mask-lifecycle control, not a production fix:
its dict.get observes the actual clipper frame and calls production flood_mask.
All production geometry gates stay enabled.
"""
import argparse
import hashlib
import inspect
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(r'D:\项目\鼻腔建模')
OUT = ROOT / 'outputs' / 'T-013'
sys.path.insert(0, str(ROOT / 'work' / 'lib'))
from partitioned_surface import clip_and_cap, SurfaceClipError
from connectivity_opened_surface import flood_mask, OPENINGS
from auto_opening_pipeline import load_planes, build_placed, plane_basis, clip_areas
from test_partitioned_surface import cube, plane


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


class DynamicSelector(dict):
    """Controlled alternate lifetime evaluated inside the unchanged production API."""
    def __init__(self, masks):
        super().__init__(masks)
        self.trace = []

    def get(self, name, default=None):
        frame = inspect.currentframe().f_back
        if frame.f_code is not clip_and_cap.__code__:
            raise RuntimeError('DynamicSelector called outside production clip_and_cap')
        local = frame.f_locals
        points, faces, spec = local['points'], local['faces'], local['spec']
        mask, note = flood_mask(points, faces, spec, seed_mode='roi')
        original = super().get(name)
        old = np.pad(original, (0, len(points) - len(original)))
        affected = np.any(mask[faces], axis=1) & np.any(local['signed'][faces] < 0, axis=1)
        cap_faces = affected & (local['patches'] != 'wall')
        tri = points[faces[cap_faces]]
        entry = {'plane': name, 'vertices': len(points), 'mask_selected': int(mask.sum()),
                 'original_mask_selected': int(old.sum()),
                 'newly_selected_original_vertices': int(np.count_nonzero(mask[:len(original)] & ~original)),
                 'newly_selected_appended_vertices': int(mask[len(original):].sum()),
                 'earlier_cap_affected_triangles': int(cap_faces.sum()),
                 'flood_note': note}
        if len(tri):
            signed = local['signed'][faces[cap_faces]]
            entry.update({'earlier_cap_patch_counts': {str(k): int(v) for k,v in
                          zip(*np.unique(local['patches'][cap_faces], return_counts=True))},
                          'earlier_cap_signed_min_mm': float(signed.min()),
                          'earlier_cap_signed_max_mm': float(signed.max()),
                          'earlier_cap_all_vertices_negative_triangles': int((signed < 0).all(axis=1).sum()),
                          'earlier_cap_straddling_triangles': int(((signed.min(axis=1) < 0) &
                                                                  (signed.max(axis=1) > 0)).sum()),
                          'earlier_cap_bounds_lps_mm': {'min': tri.min(axis=(0,1)).tolist(),
                                                       'max': tri.max(axis=(0,1)).tolist()}})
            # Store exact conflicting geometry for independent geometric replay.
            np.savez_compressed(OUT / ('collision_' + name + '.npz'),
                                triangles=tri, signed=signed, mask=mask[faces[cap_faces]],
                                patch=local['patches'][cap_faces].astype(str),
                                spec_json=np.array(json.dumps(spec)))
        self.trace.append(entry)
        return mask


def run_clip(points, faces, planes, masks, dynamic=False):
    selector = DynamicSelector(masks) if dynamic else masks
    result = {'mode': 'current_mesh_flood_control' if dynamic else 'unchanged_production',
              'production_api': 'partitioned_surface.clip_and_cap'}
    started = time.monotonic()
    try:
        p, f, labels, qc = clip_and_cap(points, faces, planes, selectors=selector)
        result.update({'passed': True, 'qc': qc, 'area_mm2': qc['caps']})
        result['array_sha256'] = {k: hashlib.sha256(v.tobytes()).hexdigest() for k,v in
                                  [('points',p),('faces',f),('labels',labels.astype('U'))]}
    except ValueError as exc:
        result.update({'passed': False, 'exception': type(exc).__name__, 'error': str(exc)})
        if isinstance(exc, SurfaceClipError):
            result['details'] = exc.details
    result['duration_s'] = time.monotonic() - started
    if dynamic:
        result['selector_trace'] = selector.trace
    return result


def synthetic():
    points, faces = cube()
    # Analytic ground truth: second plane x=2 cuts the already-created z=2 cap.
    # 4x4 cap spans x=0..4; half lies at x<2. Earlier-cap refusal is mandatory.
    overlap = {'bottom': plane([0,0,2], [0,0,1]),
               'side': plane([2,0,0], [1,0,0])}
    masks = {k: flood_mask(points,faces,spec)[0] for k,spec in overlap.items()}
    old = run_clip(points,faces,overlap,masks)
    new = run_clip(points,faces,overlap,masks,True)
    assert old['error'] == 'side: unexpected boundary outside cutting plane or ROI', old
    assert new['error'] == 'side: cutting plane intersects an earlier cap', new
    assert new['selector_trace'][-1]['newly_selected_appended_vertices'] > 0
    disjoint = {'bottom': plane([0,0,2], [0,0,1]),
                'top': plane([0,0,6], [0,0,1], False)}
    masks = {k: flood_mask(points,faces,spec)[0] for k,spec in disjoint.items()}
    a = run_clip(points,faces,disjoint,masks)
    b = run_clip(points,faces,disjoint,masks,True)
    assert a['passed'] and b['passed']
    for result in (a,b):
        assert abs(result['qc']['technical_qc']['signed_volume_mm3'] - 64) < 1e-10
        assert all(abs(result['qc']['caps'][k]['area_mm2'] - 16) < 1e-10 for k in disjoint)
    assert a['array_sha256'] == b['array_sha256']
    evidence = {'analytic_source': 'cube(): [0,4] x [0,4] x [0,8]; source test_partitioned_surface.py',
                'overlap_expected': 'earlier-cap refusal; z=2 cap intersects x=2 plane',
                'overlap_old': old, 'overlap_control': new,
                'disjoint_expected': 'two 16 mm2 caps and 64 mm3 retained volume',
                'disjoint_old': a, 'disjoint_control': b,
                'production_files_modified': False}
    record(OUT / 'synthetic_results.json', evidence)
    print(json.dumps({'synthetic_assertions': 'passed',
                      'overlap_old': old['error'], 'overlap_control': new['error']},ensure_ascii=False))


def load_mesh(path):
    import vtk
    from export_candidate_preview import triangle_arrays
    reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(str(path)); reader.Update()
    return reader.GetOutput(), triangle_arrays(reader.GetOutput())


def real_cases(cases):
    result = {'production_files_modified': False,
              'scope': 'fixed planes clipper control only; not process/N6 auto_pass', 'cases': {}}
    for case in cases:
        surface = Path('C:/ts_work/batch27_surfaces') / case / 'source_surface.vtp'
        lm = ROOT / 'work' / '06_auto_landmarks' / case / 'landmarks.json'
        inputs = {str(p): fingerprint(p) for p in [surface,lm]}
        planes, _, _, _ = load_planes(ROOT / 'work' / '06_auto_landmarks',None,case,True)
        _, (points,faces) = load_mesh(surface)
        entry = {'frozen_inputs': inputs, 'planes': planes, 'offset_source': 'original proposal at zero'}
        if case != 'p0':
            recpath = Path('C:/ts_work/batch27_opening') / (case + '.json')
            rec = json.loads(recpath.read_text(encoding='utf-8'))
            entry['recorded_decision'] = rec['decision']
            cap_path = Path('C:/ts_work/batch27_opening') / case / 'auto_placed.vtp'
            if cap_path.exists():
                poly,(cap_pts,cap_faces) = load_mesh(cap_path)
                labels = poly.GetCellData().GetAbstractArray('boundary_patch')
                label_values = np.array([labels.GetValue(i) for i in range(labels.GetNumberOfValues())])
                offsets = {}
                for k in OPENINGS:
                    n = plane_basis(planes[k]['normal_lps'])[0]
                    selected = cap_pts[np.unique(cap_faces[label_values==k])]
                    values = (selected - planes[k]['point_lps_mm']) @ n
                    assert len(values) and np.ptp(values) < 1e-6, (case,k,'stored cap not coplanar')
                    offsets[k] = float(np.mean(values))
                entry['offset_source'] = 'exact plane recovered from stored labelled cap geometry'
                inputs[str(cap_path)] = fingerprint(cap_path)
            else:
                offsets = rec['offset_from_reviewed_mm']
                entry['offset_source'] = 'rounded two-decimal historical offsets; exploratory only'
            norms = {k: plane_basis(planes[k]['normal_lps'])[0] for k in OPENINGS}
            planes = build_placed(planes,norms,{k:0.0 for k in OPENINGS},offsets)
            entry.update({'used_offsets_mm': offsets, 'recorded_areas_mm2': rec['patch_areas_mm2'],
                          'planes': planes})
        masks = {k: flood_mask(points,faces,planes[k])[0] for k in OPENINGS}
        if case == 'p0':
            k = 'nasopharynx_outlet'
            entry['outlet_alone_production'] = run_clip(points,faces,{k:planes[k]},{k:masks[k]})
            single = entry['outlet_alone_production']
            if single['passed']:
                entry['outlet_alone_area_vs_engineering_band'] = {
                    'area_mm2':single['qc']['caps'][k]['area_mm2'],
                    'configured_band_mm2':[120.0,500.0],
                    'inside_band':120.0 <= single['qc']['caps'][k]['area_mm2'] <= 500.0,
                    'interpretation':'software area check only; no anatomical diagnosis'}
        entry['baseline'] = run_clip(points,faces,planes,masks)
        record(OUT / (case + '_baseline.json'), entry)
        entry['control'] = run_clip(points,faces,planes,masks,True)
        a,b = entry['baseline'],entry['control']
        if a['passed'] and b['passed']:
            diffs = {k:b['qc']['caps'][k]['area_mm2'] - a['qc']['caps'][k]['area_mm2'] for k in OPENINGS}
            entry['comparison'] = {'area_differences_mm2': diffs,
                                  'any_area_changed_above_1e-8': any(abs(v)>1e-8 for v in diffs.values()),
                                  'all_output_array_hashes_equal':a['array_sha256']==b['array_sha256']}
        after = {p:fingerprint(p) for p in inputs}
        entry['inputs_unchanged'] = after == inputs
        if not entry['inputs_unchanged']:
            raise RuntimeError('Input fingerprints changed; evidence invalid')
        result['cases'][case] = entry
        record(OUT / 'real_cases_results.json',result)
        print(json.dumps({'case':case, 'baseline':a.get('error','passed'),
                          'control':b.get('error','passed'), 'comparison':entry.get('comparison'),
                          'offset_source':entry['offset_source']},ensure_ascii=False),flush=True)
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--synthetic',action='store_true')
    ap.add_argument('--cases',nargs='*')
    args = ap.parse_args()
    if args.synthetic:
        synthetic()
    if args.cases:
        real_cases(args.cases)
