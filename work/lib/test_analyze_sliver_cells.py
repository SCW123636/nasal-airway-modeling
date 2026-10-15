"""Regression tests for analyze_sliver_cells.

Why this file exists: on 2026-10-13 the first version of analyze_sliver_cells.py
computed a `cellDeterminant` that did NOT reproduce checkMesh's numbers
(min 7.40e-08 vs 1.11e-07, count 575 vs 585).  It reported locations anyway.  So
the tool now carries its own known-answer self-test, and these tests pin:

  * the metric implementation against an analytic value - a regular tetrahedron
    must give 8/27, because its four outward face normals are (+-1,+-1,+-1)/sqrt3
    with even sign product, whose outer-product sum is (4/3)I;
  * the exterior-face bookkeeping (a face appearing once is exterior, and the
    surface/volume must agree on where the boundary is);
  * the repair-origin mapping, which depends on the in-place 4-for-1 emission
    order in repair_boundary_tetrahedra.py:86-93 and silently produces wrong
    attributions if that ever changes.

The repair-origin test matters most: the finding "481 of the 585 flagged cells
are repair-created" rests entirely on that mapping being right.
"""
from collections import Counter
from itertools import combinations
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import analyze_sliver_cells as AS  # noqa: E402

REGULAR_TET = np.array([[1.0, 1.0, 1.0], [1.0, -1.0, -1.0],
                        [-1.0, 1.0, -1.0], [-1.0, -1.0, 1.0]])
ONE_TET = np.array([[0, 1, 2, 3]], dtype=np.int64)


# ------------------------------------------------------------------- the metric

def test_selftest_passes(capsys):
    assert AS.selftest() is True
    out = capsys.readouterr().out
    assert 'regular tetrahedron' in out and 'PASS' in out
    assert 'FAIL' not in out


def test_selftest_failure_also_returns_builtin_bool(monkeypatch):
    monkeypatch.setattr(AS, 'cell_determinant',
                        lambda *_: (np.array([0.0]), np.array([1.0])))
    assert AS.selftest() is False


def test_regular_tetrahedron_metric_is_exactly_8_over_27():
    det, _ = AS.cell_determinant(REGULAR_TET, ONE_TET)
    assert abs(det[0] - 8.0 / 27.0) < 1e-12


def test_metric_is_scale_invariant():
    """Massively scaled tets must give the same number - that is the whole point
    of normalising by the average face area."""
    det_small, _ = AS.cell_determinant(REGULAR_TET * 1e-6, ONE_TET)
    det_big, _ = AS.cell_determinant(REGULAR_TET * 1e6, ONE_TET)
    assert abs(det_small[0] - det_big[0]) < 1e-12


def test_a_sliver_has_a_near_zero_metric():
    pts = np.array([[0, 0, 0], [1, 0, 0], [0.5, 1e-9, 0], [0.5, 0, 1e-9]], dtype=float)
    det, _ = AS.cell_determinant(pts, ONE_TET)
    assert det[0] < 1e-15
    # a well-shaped tet of the same size must not
    assert AS.cell_determinant(REGULAR_TET, ONE_TET)[0][0] > 0.1


def test_metric_handles_a_negative_orientation():
    """Flipping two vertices must not change the metric (normals get re-oriented)."""
    flipped = ONE_TET[:, [0, 2, 1, 3]]
    a, _ = AS.cell_determinant(REGULAR_TET, ONE_TET)
    b, _ = AS.cell_determinant(REGULAR_TET, flipped)
    assert abs(a[0] - b[0]) < 1e-12


# ------------------------------------------------------- exterior-face bookkeeping

def _tet_with_its_faces(tags=(11, 22, 33, 44)):
    """One tet plus all four of its faces as boundary triangles."""
    tris = np.array([list(f) for f in AS.TET_FACES], dtype=np.int64)
    return REGULAR_TET, tris, np.array(tags, dtype=np.int64), ONE_TET


def test_single_tet_has_all_four_faces_exterior():
    pts, tris, tags, tets = _tet_with_its_faces()
    n_ext, ext_tag = AS.exterior_faces(tets, tris, tags, len(pts))
    assert n_ext.tolist() == [4]
    # with four exterior faces the tag is last-writer-wins, so only assert it is
    # one of the supplied tags - the count is the meaningful output
    assert int(ext_tag[0]) in set(tags.tolist())


def test_shared_face_is_interior():
    """Two tets sharing face (0,1,2): that face is interior, so each tet keeps 3
    exterior faces.  This is the case that must not be counted as boundary."""
    pts = np.vstack([REGULAR_TET, [[0.0, 0.0, 0.0]]])   # node 4 = centroid-ish
    tets = np.array([[0, 1, 2, 3], [0, 1, 2, 4]], dtype=np.int64)
    # exterior faces of the pair = the 3+3 non-shared faces
    faces = []
    for tet in tets:
        faces.extend(sorted(int(tet[i]) for i in f) for f in AS.TET_FACES)
    counts = {tuple(f): faces.count(f) for f in faces}
    shared = [f for f, c in counts.items() if c == 2]
    assert len(shared) == 1, 'the two tets must share exactly one face'
    boundary = [f for f, c in counts.items() if c == 1]
    tris = np.array(boundary, dtype=np.int64)
    tags = np.full(len(tris), 7, dtype=np.int64)
    n_ext, _ = AS.exterior_faces(tets, tris, tags, len(pts))
    assert n_ext.tolist() == [3, 3]


def _enumerated_boundary(tets):
    """Independent oracle: enumerate vertex combinations per tet, without the
    production face table, flattened arrays or numeric face-key encoding."""
    cell_faces = [[tuple(sorted(face)) for face in combinations(map(int, tet), 3)]
                  for tet in tets]
    incidence = Counter(face for faces in cell_faces for face in faces)
    boundary = sorted(face for face, count in incidence.items() if count == 1)
    tag_by_face = {face: 101 + i for i, face in enumerate(boundary)}
    counts = [sum(incidence[face] == 1 for face in faces) for faces in cell_faces]
    single_tags = [tag_by_face[next(face for face in faces if incidence[face] == 1)]
                   if count == 1 else 0
                   for faces, count in zip(cell_faces, counts)]
    return np.asarray(boundary), np.asarray(list(tag_by_face.values())), counts, single_tags


@pytest.mark.parametrize('tet_order', [(0, 1, 2, 3, 4), (4, 2, 0, 3, 1), (4, 3, 2, 1, 0)])
@pytest.mark.parametrize('reverse_face_table', [False, True])
@pytest.mark.parametrize('reverse_boundary', [False, True])
def test_asymmetric_exterior_counts_and_single_patch_survive_permutations(
        tet_order, reverse_face_table, reverse_boundary, monkeypatch):
    # Three neighbours cover central faces 012, 013, 023; only face 123 is
    # exterior on cell 0.  Cell 4 is isolated.  Expected counts are asymmetric.
    original = np.array([[0, 1, 2, 3], [0, 1, 2, 4], [0, 1, 3, 5],
                         [0, 2, 3, 6], [7, 8, 9, 10]], dtype=np.int64)
    tets = original[list(tet_order)]
    triangles, tags, expected_counts, expected_tags = _enumerated_boundary(tets)
    assert expected_counts == np.array([1, 3, 3, 3, 4])[list(tet_order)].tolist()
    if reverse_face_table:
        monkeypatch.setattr(AS, 'TET_FACES', tuple(reversed(AS.TET_FACES)))
        tets = tets[:, [2, 0, 3, 1]]  # local vertex order is also irrelevant
    if reverse_boundary:
        triangles, tags = triangles[::-1, ::-1], tags[::-1]
    counts, patch_tags = AS.exterior_faces(tets, triangles, tags, 11)
    assert counts.tolist() == expected_counts
    for index, count in enumerate(expected_counts):
        if count == 1:
            assert patch_tags[index] == expected_tags[index]


def test_fully_surrounded_tet_has_no_exterior_patch():
    tets = np.array([[0, 1, 2, 3], [0, 1, 2, 4], [0, 1, 3, 5],
                     [0, 2, 3, 6], [1, 2, 3, 7]], dtype=np.int64)
    triangles, tags, expected_counts, _ = _enumerated_boundary(tets)
    assert expected_counts == [0, 3, 3, 3, 3]
    counts, patch_tags = AS.exterior_faces(tets, triangles, tags, 8)
    assert counts.tolist() == expected_counts
    assert patch_tags[0] == 0


def test_surface_volume_disagreement_is_fatal():
    """If the triangle list does not cover the volume exterior exactly, stop -
    rather than silently analysing the wrong boundary."""
    pts, tris, tags, tets = _tet_with_its_faces()
    with pytest.raises(SystemExit):
        AS.exterior_faces(tets, tris[:-1], tags[:-1], len(pts))


def test_duplicate_triangles_are_fatal():
    pts, tris, tags, tets = _tet_with_its_faces()
    dup = np.vstack([tris, tris[:1]])
    with pytest.raises(SystemExit):
        AS.exterior_faces(tets, dup, np.append(tags, tags[0]), len(pts))


# ---------------------------------------------------------- repair origin mapping

def test_repair_origin_interleaves_a_split_in_place():
    """repair_boundary_tetrahedra.py:86-93 emits 4 cells for a split cell and 1
    otherwise, in input order - NOT all new cells appended at the end."""
    origin = AS.repair_origin(n_output=6, split_cell_indices=[1], n_input=3)
    assert origin.tolist() == [0, 1, 1, 1, 1, 2]


def test_repair_origin_with_no_splits_is_the_identity():
    origin = AS.repair_origin(n_output=4, split_cell_indices=[], n_input=4)
    assert origin.tolist() == [0, 1, 2, 3]


def test_repair_origin_covers_every_output_cell():
    """Retain the b15 count contract, with a complete synthetic 4,444-item
    split list.  These indices are a fixture, not the patient's actual map."""
    split_indices = np.linspace(0, 1147861, 4444, dtype=np.int64)
    assert len(np.unique(split_indices)) == 4444
    origin = AS.repair_origin(n_output=1161194, split_cell_indices=split_indices,
                              n_input=1147862)
    assert len(origin) == 1161194
    assert np.array_equal(np.unique(origin), np.arange(1147862))
    expected_counts = np.ones(1147862, dtype=np.int64)
    expected_counts[split_indices] = 4
    assert np.array_equal(np.bincount(origin, minlength=1147862), expected_counts)


def test_repair_origin_rejects_incomplete_split_count():
    # The previous fixture supplied only three splits for an output requiring
    # four.  Keep the inconsistency as an explicit negative case.
    with pytest.raises(SystemExit, match='produced 21 of 24 cells'):
        AS.repair_origin(n_output=24, split_cell_indices=[0, 5, 11], n_input=12)


def test_repair_origin_matches_real_small_repair_output(tmp_path):
    import meshio
    from repair_boundary_tetrahedra import repair

    # Four subtets fill one regular tetrahedron, each with one exterior face.
    # Put a disjoint four-exterior-face tet between them so only input cell 1
    # must actually split, and its output must stay interleaved in that place.
    points = np.vstack([REGULAR_TET, REGULAR_TET.mean(axis=0), REGULAR_TET + 5.0])
    children = [list(face) + [4] for face in combinations(range(4), 3)]
    tets = np.array([children[0], [5, 6, 7, 8], *children[1:]], dtype=np.int64)
    triangles, _, expected_counts, _ = _enumerated_boundary(tets)
    assert expected_counts == [1, 4, 1, 1, 1]
    tags = 1 + np.arange(len(triangles)) % 4
    cell_tags = [tags, np.full(len(tets), 5)]
    field_data = {name: np.array([tag, 3 if name == 'fluid' else 2])
                  for name, tag in {'nostril_L': 1, 'nostril_R': 2,
                                    'nasopharynx_outlet': 3, 'wall': 4, 'fluid': 5}.items()}
    source, target = tmp_path / 'source.msh', tmp_path / 'repaired.msh'
    meshio.write(source, meshio.Mesh(points, [('triangle', triangles), ('tetra', tets)],
                 cell_data={'gmsh:physical': cell_tags, 'gmsh:geometrical': cell_tags},
                 field_data=field_data), file_format='gmsh22', binary=False)
    report = repair(source, target)
    assert report['split_cell_indices'] == [1]
    assert report['input_cells'] == 5 and report['output_cells'] == 8
    origin = AS.repair_origin(report['output_cells'], report['split_cell_indices'],
                              report['input_cells'])
    assert origin.tolist() == [0, 1, 1, 1, 1, 2, 3, 4]
    output = meshio.read(target)
    for output_tet, input_index in zip(output.cells_dict['tetra'], origin):
        if input_index == 1:
            assert 9 in output_tet
            assert set(output_tet) - {9} <= set(tets[input_index])
        else:
            assert set(output_tet) == set(tets[input_index])
    counts, patch_tags = AS.exterior_faces(output.cells_dict['tetra'], triangles,
                                          tags, len(output.points))
    assert counts.tolist() == [1] * 8
    assert sorted(patch_tags.tolist()) == sorted(tags.tolist())


def test_repair_origin_rejects_a_span_overrun():
    """A wrong split list must fail loudly, not attribute cells to the wrong input."""
    with pytest.raises(SystemExit):
        AS.repair_origin(n_output=5, split_cell_indices=[1], n_input=3)


# ------------------------------------------------------------------------- parsing

def test_read_set_parses_an_openfoam_set_file(tmp_path):
    f = tmp_path / 'underdeterminedCells'
    f.write_text(
        '/*--------------------------------*- C++ -*----------------*\\\n'
        'FoamFile\n{\n    class       cellSet;\n}\n'
        '// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //\n\n'
        '\n585\n(\n409603\n327685\n1114146\n)\n\n'
        '// ************************************ //\n')
    idx = AS.read_set(f)
    assert idx.tolist() == [409603, 327685, 1114146]


def test_read_msh_roundtrip(tmp_path):
    """The parser must invert what the writer imposes: 1-based ids, tag then
    geometry, nodes before elements."""
    pts, tris, tags, tets = _tet_with_its_faces()
    msh = tmp_path / 'tiny.msh'
    lines = ['$MeshFormat', '2.2 0 8', '$EndMeshFormat', '$Nodes', str(len(pts))]
    for i, p in enumerate(pts, 1):
        lines.append(f'{i} {p[0]:.17g} {p[1]:.17g} {p[2]:.17g}')
    lines += ['$EndNodes', '$Elements', str(len(tris) + len(tets))]
    eid = 0
    for tri, tag in zip(tris, tags):
        eid += 1
        lines.append(f'{eid} 2 2 {tag} {tag} {tri[0] + 1} {tri[1] + 1} {tri[2] + 1}')
    for tet in tets:
        eid += 1
        lines.append(f'{eid} 4 2 5 5 {tet[0] + 1} {tet[1] + 1} {tet[2] + 1} {tet[3] + 1}')
    lines += ['$EndElements']
    msh.write_text('\n'.join(lines) + '\n', encoding='ascii')

    rp, rtris, rtags, rtets = AS.read_msh(msh)
    assert np.allclose(rp, pts)
    assert rtris.tolist() == tris.tolist()
    assert rtags.tolist() == tags.tolist()
    assert rtets.tolist() == tets.tolist()
