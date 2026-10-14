"""Exercise surface_gate on the real geometry, including known-bad inputs.

A gate that has only ever been shown passing is not evidence. This runs it over
four surfaces: the two sliver-repaired meshes, plus two deliberately broken
meshes (a mesh with a hole, and one with a collapsed patch) to confirm the gate
actually fails when it should.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patch_compare import parse_stl_regions
from decide_selfintersection_precision import build_topology
from surface_gate import evaluate

REPAIRED = Path('D:/项目/鼻腔建模/.tools/sliver-repair-20261011')
NATIVE = Path('D:/项目/鼻腔建模/.tools/sliver-repair-20261011/native2')
CASES = {
    'p2_repaired': (REPAIRED / 'p2/combined_repaired.stl', 115),
    'p3t1_repaired': (REPAIRED / 'p3t1/combined_repaired.stl', 194),
}
OPENINGS = ('nostril_L', 'nostril_R', 'nasopharynx_outlet')


def load(path):
    tris, labels = parse_stl_regions(path)
    verts, faces = build_topology(np.array(tris, dtype=np.float64))
    return verts, faces, labels


def punch_hole(points, faces, n=40):
    """Delete a patch of faces to create boundary edges."""
    keep = np.ones(len(faces), bool)
    keep[:n] = False
    used = np.unique(faces[keep])
    remap = -np.ones(len(points), np.int64)
    remap[used] = np.arange(len(used))
    return points[used], remap[faces[keep]]


def main():
    print('=' * 22, 'A. repaired surfaces (expect pass)')
    for case, (path, native) in CASES.items():
        v, f, lab = load(path)
        rep = evaluate(v, f, v, f, lab, OPENINGS, native_self_intersection=native, unit_scale=1e6)
        print(f"  {case}: {rep['decision']}  failures={[x['gate'] for x in rep['failures']]}")
        print(f"     openings={ {k: x['area_mm2'] for k, x in rep['openings'].items()} }")
        print(f"     native_advisory={rep['advisory']['locations']}")

    print('=' * 22, 'B. deliberately broken meshes (expect fail)')
    v, f, lab = load(REPAIRED / 'p2/combined_repaired.stl')

    v2, f2 = punch_hole(v, f, 40)
    lab2 = [str(l) for l in lab[40:]]
    rep = evaluate(v, f, v2, f2, lab2, OPENINGS, unit_scale=1e6)
    print(f"  mesh with hole: {rep['decision']}")
    for x in rep['failures']:
        print('     ', x)

    lab3 = [str(l) for l in lab]
    for i, name in enumerate(lab3):
        if name == 'nasopharynx_outlet':
            lab3[i] = 'wall'
    rep = evaluate(v, f, v, f, lab3, OPENINGS, unit_scale=1e6)
    print(f"  outlet patch erased: {rep['decision']}")
    for x in rep['failures']:
        print('     ', x)

    print('=' * 22, 'C. enforcement rollback (expect fail on repaired p3t1)')
    import surface_gate
    surface_gate.NATIVE_SELF_INTERSECTION_ENFORCE = True
    v, f, lab = load(REPAIRED / 'p3t1/combined_repaired.stl')
    rep = evaluate(v, f, v, f, lab, OPENINGS, native_self_intersection=194, unit_scale=1e6)
    print(f"  enforced: {rep['decision']} failures={[x['gate'] for x in rep['failures']]}")


if __name__ == '__main__':
    main()