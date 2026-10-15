"""Small, single-thread controls. Never loads patient meshes or invokes WSL."""
from collections import Counter
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
from itertools import combinations
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def oracle(tets):
    # Independent per-tet set enumeration; no production face table/key/layout.
    faces_by_cell = [[tuple(sorted(face)) for face in combinations(map(int, tet), 3)]
                     for tet in tets]
    owners = Counter(face for cell in faces_by_cell for face in cell)
    boundary = sorted(face for face, count in owners.items() if count == 1)
    physical_tags = {face: 200 + 7 * i for i, face in enumerate(boundary)}
    counts, single = [], {}
    for index, faces in enumerate(faces_by_cell):
        exterior = [face for face in faces if owners[face] == 1]
        counts.append(len(exterior))
        if len(exterior) == 1:
            single[index] = physical_tags[exterior[0]]
        elif not exterior:
            single[index] = 0
    return np.asarray(boundary), np.asarray(list(physical_tags.values())), counts, single


def run(module):
    records = []
    star = np.array([[0, 1, 2, 3], [0, 1, 2, 4], [0, 1, 3, 5],
                     [0, 2, 3, 6], [7, 8, 9, 10]], dtype=np.int64)
    inputs = [('asymmetric_single_patch', star, [1, 3, 3, 3, 4]),
              ('shared_pair', np.array([[0, 1, 2, 3], [0, 1, 2, 4]]), [3, 3]),
              ('interior_zero_tag', np.array([[0, 1, 2, 3], [0, 1, 2, 4],
                [0, 1, 3, 5], [0, 2, 3, 6], [1, 2, 3, 7]]), [0, 3, 3, 3, 3])]
    original_table = module.TET_FACES
    for name, original, explicit in inputs:
        permutations = [list(range(len(original))), list(reversed(range(len(original))))]
        if name == 'asymmetric_single_patch':
            permutations.append([4, 2, 0, 3, 1])
        for order in permutations:
            tets = original[order]
            triangles, tags, expected, single = oracle(tets)
            assert expected == [explicit[index] for index in order]
            for reverse_table in (False, True):
                module.TET_FACES = original_table[::-1] if reverse_table else original_table
                for reverse_triangles in (False, True):
                    actual_triangles = triangles[::-1, ::-1] if reverse_triangles else triangles
                    actual_tags = tags[::-1] if reverse_triangles else tags
                    stdout = io.StringIO()
                    with redirect_stdout(stdout):
                        counts, patch = module.exterior_faces(
                            tets, actual_triangles, actual_tags, int(tets.max()) + 1)
                    single_actual = {index: int(patch[index]) for index in single}
                    records.append({'case': name, 'tet_order': order,
                        'reverse_face_table': reverse_table, 'reverse_triangles': reverse_triangles,
                        'expected_counts': expected, 'actual_counts': counts.tolist(),
                        'expected_unambiguous_tags': single, 'actual_unambiguous_tags': single_actual,
                        'passed': counts.tolist() == expected and single_actual == single,
                        'stdout': stdout.getvalue()})
    module.TET_FACES = original_table
    with redirect_stdout(io.StringIO()):
        value = module.selftest()
    return {'controls': records, 'passed': sum(record['passed'] for record in records),
            'total': len(records), 'selftest': {'value': bool(value),
            'type': type(value).__module__ + '.' + type(value).__name__,
            'builtin_bool': type(value) is bool}}


def main():
    paths = {'before': HERE / 'baseline/analyze_sliver_cells.py',
             'after': ROOT / 'work/lib/analyze_sliver_cells.py'}
    modules = {label: load('sliver_' + label, path) for label, path in paths.items()}
    result = {'schema': 't028_small_known_answers/v1',
              'inputs': {label: {'path': str(path), 'sha256': sha(path)}
                         for label, path in paths.items()},
              'script_sha256': sha(Path(__file__).resolve()),
              'patient_mesh_loaded': False, 'wsl_invoked': False,
              'known_checkmesh_constants_unchanged': modules['before'].KNOWN == modules['after'].KNOWN,
              'before': run(modules['before']), 'after': run(modules['after'])}
    result['baseline_defects_reproduced'] = (result['before']['passed'] < result['before']['total']
                                            and not result['before']['selftest']['builtin_bool'])
    result['acceptance_passed'] = (result['after']['passed'] == result['after']['total']
                                  and result['after']['selftest']['builtin_bool']
                                  and result['known_checkmesh_constants_unchanged'])
    (HERE / 'known_answers.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                                            encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ('before', 'after')}, ensure_ascii=False))
    print(json.dumps({label: {key: value for key, value in result[label].items()
                             if key != 'controls'} for label in ('before', 'after')}, ensure_ascii=False))
    assert result['baseline_defects_reproduced']
    assert result['acceptance_passed']


if __name__ == '__main__':
    main()
