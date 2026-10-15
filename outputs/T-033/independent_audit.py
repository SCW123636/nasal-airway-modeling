"""T-033 read-only independent checks; never runs inference or edits inputs.

Writes only a new evidence directory below this script's own output scope.
"""
from pathlib import Path
import argparse, ast, datetime, hashlib, json, os, sys, traceback

for variable in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'
import numpy as np
import SimpleITK as sitk

ROOT = Path(r'D:\项目\鼻腔建模')
SCOPE = ROOT / 'outputs/T-033'
AUTHOR = ROOT / 'outputs/T-032'
RAW = Path(r'C:\ts_work\t032_hypopharynx\01_p2_no_crop')
SITE = Path(r'C:\Users\lenovo\.workbuddy\binaries\python\envs\nasal-cfd\Lib\site-packages\totalsegmentator')

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def image_geometry(image):
    return {'size_xyz': list(image.GetSize()), 'spacing_xyz': list(image.GetSpacing()),
            'origin_lps_mm': list(image.GetOrigin()), 'direction': list(image.GetDirection()),
            'index0_center_lps_mm': list(image.TransformIndexToPhysicalPoint((0, 0, 0))),
            'last_center_lps_mm': list(image.TransformIndexToPhysicalPoint(tuple(v - 1 for v in image.GetSize())))}

def extract_function(path, name, namespace):
    tree = ast.parse(Path(path).read_text(encoding='utf-8-sig'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if not out.is_relative_to(SCOPE.resolve()):
        raise ValueError('Independent evidence directory outside T-033 scope')
    out.mkdir(parents=True, exist_ok=False)
    report = {'created': datetime.datetime.now().astimezone().isoformat(),
              'role': 'fresh independent verifier; read-only; no inference',
              'checks': [], 'facts': {}, 'failures': []}

    def check(name, actual, expected=True):
        if isinstance(actual, np.generic):
            actual = actual.item()
        passed = actual == expected
        entry = {'name': name, 'actual': actual, 'expected': expected, 'pass': bool(passed)}
        report['checks'].append(entry)
        if not passed:
            report['failures'].append(entry)

    try:
        runner = AUTHOR / 'run_isolated_semantic.py'
        # Independent expected answers exercise the actual helper, without importing
        # or executing its driver/preflight/model code.
        air_fn = extract_function(runner, 'semantic_air', {})
        hu = np.array([[[-301., -300., -299., -1000., np.nan, -1000.]]])
        labels = np.array([[[13, 13, 13, 12, 13, 0]]], dtype=np.uint8)
        check('known_answer_class13_strict_lt_minus300', air_fn(hu, labels).tolist(), [[[True, False, False, False, False, False]]])
        check('known_answer_empty_label', int(air_fn(hu, np.zeros_like(labels)).sum()), 0)
        try:
            air_fn(hu, np.zeros((1, 1, 2)))
        except ValueError:
            rejected = True
        else:
            rejected = False
        check('known_answer_shape_mismatch_rejected', rejected)

        image = sitk.Image([3, 4, 5], sitk.sitkUInt8)
        image.SetSpacing((2., 3., 4.)); image.SetOrigin((10., 20., 30.))
        image.SetDirection((0., -1., 0., 1., 0., 0., 0., 0., 1.))
        check('known_answer_oblique_LPS_index_xyz', list(image.TransformIndexToPhysicalPoint((1, 2, 3))), [4., 22., 42.])
        helper = extract_function(AUTHOR / 'inspect_lower_coverage.py', 'label_info', {'np': np})
        toy = np.zeros((5, 4, 3), dtype=np.uint8); toy[3, 2, 1] = 1
        measured = helper(toy, image)
        check('known_answer_bbox_xyz_not_numpy_zyx', measured['bbox_ijk_xyz'], [(1, 2, 3), (1, 2, 3)])
        check('known_answer_bbox_LPS', measured['bbox_centers_lps_mm'], [(4., 22., 42.), (4., 22., 42.)])
        check('known_answer_voxel_count', int(measured['voxels']), 1)
        check('known_answer_empty_bbox', helper(np.zeros_like(toy), image)['bbox_ijk_xyz'], None)

        status = read_json(RAW / 'run_status.json')
        author_copy = read_json(AUTHOR / 'runs/02_p2_no_crop_result/run_status.json')
        check('copied_status_matches_raw', author_copy, status)
        check('actual_run_status', status['status'], 'diagnostic_completed')
        check('symptom_identity_unknown', status['symptom_patient_mapping'], 'unknown')
        check('medical_review_pending', status['medical_review'], 'pending')
        check('CFD_not_admitted', status['cfd_admission'], False)
        for name, expected in status['inputs'].items():
            check('input_fingerprint_' + name, digest(expected['path']), expected['sha256'])
        for name, expected in status['output_sha256'].items():
            check('raw_output_fingerprint_' + name, digest(RAW / name), expected)

        # Installed files and cached model metadata, not the author's summary,
        # establish that class 13 and the selected weights refer to hypopharynx.
        dataset = read_json(status['inputs']['dataset']['path'])
        check('model_dataset_hypopharynx_class', dataset['labels']['hypopharynx'], 13)
        check('model_dataset_oropharynx_class', dataset['labels']['oropharynx'], 12)
        map_tree = ast.parse((SITE / 'map_to_binary.py').read_text(encoding='utf-8-sig'))
        mapped = None
        for node in ast.walk(map_tree):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'class_map' for t in node.targets):
                mapped = ast.literal_eval(node.value)['head_glands_cavities']
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == 'class_map' and ast.literal_eval(t.slice) == 'head_glands_cavities' for t in node.targets):
                mapped = ast.literal_eval(node.value)
        check('installed_map_class13', mapped[13], 'hypopharynx')
        check('installed_map_class12', mapped[12], 'oropharynx')
        calls = [n for n in ast.walk(ast.parse(runner.read_text(encoding='utf-8-sig'))) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'nnUNet_predict_image']
        check('exactly_one_model_call', len(calls), 1)
        call = calls[0]; keywords = {k.arg: ast.unparse(k.value) for k in call.keywords}
        check('actual_model_task775', ast.literal_eval(call.args[2]), 775)
        check('actual_crop_none', keywords['crop'], 'None')
        check('actual_task_name', ast.literal_eval(next(k.value for k in call.keywords if k.arg == 'task_name')), 'head_glands_cavities')
        check('actual_output_task_name', ast.literal_eval(next(k.value for k in call.keywords if k.arg == 'output_task_name')), 'head_glands_cavities')
        check('actual_no_roi_subset_keyword', 'roi_subset' in keywords, False)
        nn_tree = ast.parse((SITE / 'nnunet.py').read_text(encoding='utf-8-sig'))
        nn_function = next(n for n in nn_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'nnUNet_predict_image')
        crop_blocks = [n for n in ast.walk(nn_function) if isinstance(n, ast.If) and ast.unparse(n.test) == 'crop is not None']
        check('installed_crop_guard_contains_crop_to_mask', any('crop_to_mask(img_in' in ast.unparse(n) for n in crop_blocks))
        report['facts']['installed_crop_guards_lines'] = [n.lineno for n in crop_blocks]
        report['facts']['actual_model_keywords'] = keywords

        # The old log is direct evidence that its crop did not remove any z slice.
        oldlog = Path(r'C:\ts_work\p2\ts_run.log').read_text(encoding='utf-8-sig', errors='replace')
        newlog = (AUTHOR / 'p2_no_crop_inference.log').read_text(encoding='utf-8-sig', errors='replace')
        check('old_command_includes_full_head_glands_task', '-ta head_glands_cavities' in oldlog)
        check('old_log_created_hypopharynx', 'Creating hypopharynx.nii.gz' in oldlog)
        check('old_crop_kept_all286_z_slices', 'cropping from (512, 512, 286) to (436, 454, 286)' in oldlog)
        check('new_resampled_full512x512x286', 'from shape (512, 512, 286)' in newlog)
        check('new_log_no_skull_crop_message', 'cropping from' in newlog, False)
        check('new_log_completed_tiles', '27/27' in newlog)
        check('new_log_export_completed', 'Segmentation export complete.' in newlog)
        check('copied_log_exact_bytes', digest(AUTHOR / 'p2_no_crop_inference.log'), digest(AUTHOR / 'runs/02_p2_no_crop_result/p2_no_crop_inference.log'))
        report['facts']['old_crop_scope'] = 'x/y changed 512x512 to 436x454; z remained286, so no evidence of inferior z truncation caused by old crop'
        report['facts']['logs_sha256'] = {'old': digest(Path(r'C:\ts_work\p2\ts_run.log')), 'new': digest(AUTHOR / 'p2_no_crop_inference.log')}

        ct_image = sitk.ReadImage('C:/ts_work/p2/ct.nii.gz')
        seg_image = sitk.ReadImage(str(RAW / 'semantic_775_nocrop.nii.gz'))
        check('raw_semantic_exact_original_grid', image_geometry(seg_image), image_geometry(ct_image))
        ct = sitk.GetArrayFromImage(ct_image); seg = sitk.GetArrayFromImage(seg_image)
        counts = {str(int(k)): int(v) for k, v in zip(*np.unique(seg, return_counts=True))}
        check('all_actual_label_counts_match_status', counts, status['label_counts'])
        check('raw_class13_nonzero_count', int(np.count_nonzero(seg == 13)), 0)
        expected_air = (seg == 13) & (ct < -300.)
        report['facts']['raw_label_counts'] = counts
        for name, expected in [('hypopharynx_semantic.nii.gz', seg == 13), ('hypopharynx_air_candidate.nii.gz', expected_air)]:
            im = sitk.ReadImage(str(RAW / name)); array = sitk.GetArrayFromImage(im)
            check(name + '_exact_CT_grid', image_geometry(im), image_geometry(ct_image))
            check(name + '_raw_values_only_zero', np.unique(array).tolist(), [0])
            check(name + '_exact_voxel_equality', bool(np.array_equal(array, expected.astype(array.dtype))))
        comparisons = {}
        for name, label in [('oropharynx', 12), ('hypopharynx', 13)]:
            im = sitk.ReadImage('C:/ts_work/p2/masks/' + name + '.nii.gz')
            check(name + '_old_grid_matches_CT', image_geometry(im), image_geometry(ct_image))
            old = sitk.GetArrayFromImage(im) > 0; new = seg == label
            comparisons[name] = {'old_voxels': int(np.count_nonzero(old)), 'new_voxels': int(np.count_nonzero(new)),
                                 'symmetric_difference': int(np.count_nonzero(old != new)), 'intersection': int(np.count_nonzero(old & new))}
            check(name + '_new_old_comparison', comparisons[name], status[name + '_old_new_comparison'])
        report['facts']['raw_comparisons'] = comparisons
        report['facts']['p2_new_oropharynx_inferior_face_voxels'] = int(np.count_nonzero(seg[0] == 12))
        del ct, seg, expected_air

        # Check original data against the earlier independent workbench baseline.
        original_integrity = []
        for record in read_json(ROOT / 'outputs/T-030/original-input-integrity.json'):
            path = Path(record['path']); exists = path.is_file()
            check('original_exists_' + str(path), exists, record['expected_exists'])
            row = {'path': str(path), 'exists': exists}
            if exists:
                row['sha256'] = digest(path)
                check('original_hash_' + str(path), row['sha256'], record['sha256_now'])
            original_integrity.append(row)
        report['facts']['original_integrity'] = original_integrity
        manifest_path = ROOT / 'outputs/T-030/assets-v1/manifest.json'
        manifest = read_json(manifest_path)
        check('workbench_case_still_p3', manifest['case'], 'p3')
        check('workbench_medical_not_reviewed', manifest['clinical_review'], 'not_reviewed')
        check('workbench_outlet_not_selected', manifest['outlet_selected'], False)
        check('workbench_CFD_not_admitted', manifest['CFD_admitted'], False)
        for name, metadata in manifest['assets'].items():
            check('workbench_asset_hash_' + name, digest(manifest_path.parent / name), metadata['sha256'])
        report['facts']['workbench_manifest_sha256'] = digest(manifest_path)

        # Independently remeasure five existing lower-field labels and report the
        # scan coordinates without assigning an anatomical hypopharynx boundary.
        coverage = read_json(AUTHOR / 'runs/01_lower_coverage/coverage.json')
        cases = {}
        for case, reference in coverage['cases'].items():
            base = Path('C:/ts_work') / case
            image = sitk.ReadImage(str(base / 'ct.nii.gz'))
            geom = image_geometry(image)
            check(case + '_coverage_geometry', geom, reference['geometry'])
            check(case + '_identity_LPS_direction', geom['direction'], [1., 0., 0., 0., 1., 0., 0., 0., 1.])
            origin = np.array(image.GetOrigin()); spacing = np.array(image.GetSpacing()); size = np.array(image.GetSize())
            bounds = [list(origin - spacing / 2), list(origin + (size - .5) * spacing)]
            check(case + '_outer_bounds_LPS', bounds, reference['voxel_outer_bounds_lps_mm'])
            cases[case] = {'geometry': geom, 'labels': {}}
            for label, expected in reference['labels'].items():
                path = base / 'masks' / (label + '.nii.gz')
                check(case + '_' + label + '_hash', digest(path), expected['sha256'])
                mask_image = sitk.ReadImage(str(path))
                check(case + '_' + label + '_grid', image_geometry(mask_image), geom)
                array = sitk.GetArrayFromImage(mask_image) > 0
                coordinates = np.argwhere(array)
                count = int(coordinates.shape[0])
                check(case + '_' + label + '_voxels', count, expected['voxels'])
                row = {'voxels': count, 'inferior_face_voxels': int(np.count_nonzero(array[0]))}
                if count:
                    low_zyx, high_zyx = coordinates.min(axis=0), coordinates.max(axis=0)
                    bbox = [low_zyx[::-1].tolist(), high_zyx[::-1].tolist()]
                    physical = [list(image.TransformIndexToPhysicalPoint(tuple(int(v) for v in point))) for point in bbox]
                    check(case + '_' + label + '_bbox_xyz', bbox, expected['bbox_ijk_xyz'])
                    check(case + '_' + label + '_bbox_LPS', physical, expected['bbox_centers_lps_mm'])
                    check(case + '_' + label + '_inferior_face', row['inferior_face_voxels'], expected['inferior_face_voxels'])
                    row['bbox_xyz'] = bbox
                else:
                    check(case + '_' + label + '_empty_bbox', expected['bbox_ijk_xyz'], None)
                cases[case]['labels'][label] = row
                del array, coordinates
            oro_image = sitk.ReadImage(str(base / 'masks/oropharynx.nii.gz'))
            coordinates = np.argwhere(sitk.GetArrayFromImage(oro_image) > 0)
            indices = {'sagittal_x': int(np.median(coordinates[:, 2])), 'coronal_y': int(np.median(coordinates[:, 1])), 'axial_z': 0}
            check(case + '_display_plane_indices', indices, reference['display_indices'])
            del coordinates
        report['facts']['five_case_direct_measurements'] = cases
        exact = read_json(AUTHOR / 'runs/02_p2_no_crop_result/exact_result_check.json')
        check('exact_result_ct_hash', exact['ct_sha256'], digest(Path('C:/ts_work/p2/ct.nii.gz')))
        check('exact_result_no_display_admission', exact['hypopharynx_display_admission'], False)
        check('exact_result_no_CFD_admission', exact['cfd_admission'], False)
        check('exact_result_new_oropharynx_voxels', exact['new_oropharynx_voxels'], comparisons['oropharynx']['new_voxels'])
        check('exact_result_new_oropharynx_face', exact['new_oropharynx_inferior_face_voxels'], report['facts']['p2_new_oropharynx_inferior_face_voxels'])
        check('exact_result_preview_hash', exact['preview_sha256'], digest(AUTHOR / 'runs/02_p2_no_crop_result/p2_real_no_crop_comparison.png'))
        report['source_snapshot'] = {str(path): digest(path) for path in [runner, AUTHOR / 'inspect_lower_coverage.py', AUTHOR / 'review_no_crop_result.py', AUTHOR / 'runs/01_lower_coverage/coverage.json', AUTHOR / 'runs/02_p2_no_crop_result/exact_result_check.json', RAW / 'run_status.json']}
    except Exception as error:
        report['exception'] = repr(error)
        report['traceback'] = traceback.format_exc()
        report['failures'].append({'exception': repr(error)})
    report['summary'] = {'checks': len(report['checks']), 'failures': len(report['failures']),
                         'interpretation': ('Independent verification incomplete; inspect failures.' if report['failures'] else 'No nonempty hypopharynx candidate; actual full-field TS775 attempt completed. Does not establish anatomical absence or complete CT coverage.')}
    (out / 'independent-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False))
    if report['failures']:
        print(json.dumps(report['failures'], ensure_ascii=False))
        sys.exit(1)

if __name__ == '__main__':
    main()
