# -*- coding: utf-8 -*-
"""Compare per-patch area / connectivity / bbox before and after a repair.

A short-edge collapse that removes triangles from a boundary patch (e.g. the
nasopharynx outlet cap) is only acceptable if the patch still covers the same
region: area and bbox essentially unchanged, still connected.
"""
import sys, json, argparse
import numpy as np

sys.path.insert(0, __file__.rsplit('\\', 1)[0])
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from decide_selfintersection_precision import parse_stl, build_topology


def parse_stl_regions(path):
    """Parse an ASCII STL keeping the `solid <region>` blocks.

    Returns (tris, labels) where tris is a list of (3,3) float arrays.
    Binary STL has no regions; falls back to a single region "ALL".
    """
    with open(path, 'rb') as f:
        head = f.read(80)
    # binary heuristic: try parse triangle count
    import struct
    try:
        text = open(path, 'r', encoding='utf-8', errors='replace').read(4000)
    except Exception:
        text = ''
    if 'solid' in text and 'facet' in text:
        tris, labels = [], []
        cur = 'ALL'
        verts = []
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                s = line.strip()
                if s.startswith('solid'):
                    cur = s.split(None, 1)[1] if len(s.split(None, 1)) > 1 else 'ALL'
                elif s.startswith('vertex'):
                    verts.append([float(x) for x in s.split()[1:4]])
                    if len(verts) == 3:
                        tris.append(np.array(verts, dtype=np.float64))
                        labels.append(cur)
                        verts = []
        return tris, labels
    # binary
    with open(path, 'rb') as f:
        data = f.read()
    n = struct.unpack('<I', data[80:84])[0]
    tris, labels = [], ['ALL'] * n
    off = 84
    for i in range(n):
        rec = data[off:off + 50]
        off += 50
        v = struct.unpack('<12f', rec[0:48])
        verts = [np.array(v[3:6]), np.array(v[6:9]), np.array(v[9:12])]
        tris.append(np.array(verts, dtype=np.float64))
    return tris, labels


def load(path):
    tris, labels = parse_stl_regions(path)
    verts, faces = build_topology(np.array(tris, dtype=np.float64))
    return verts, faces, labels


def patch_stats(verts, faces, labels, idx):
    v = verts[faces[idx]]
    a = v[:, 1] - v[:, 0]; b = v[:, 2] - v[:, 0]
    area = float(np.linalg.norm(np.cross(a, b), axis=1).sum() * 0.5)
    pts = v.reshape(-1, 3)
    return {
        "triangles": int(len(idx)),
        "area_mm2": area * 1e6,
        "bbox_min_mm": [float(x) for x in pts.min(axis=0) * 1e3],
        "bbox_max_mm": [float(x) for x in pts.max(axis=0) * 1e3],
        "components": int(n_components(faces[idx])),
    }


def n_components(sub_faces):
    parent = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for f in sub_faces:
        for v in f:
            v = int(v)
            if v not in parent:
                parent[v] = v
        union(int(f[0]), int(f[1]))
        union(int(f[1]), int(f[2]))
    return len({find(k) for k in parent})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--before', required=True)
    ap.add_argument('--after', required=True)
    ap.add_argument('--output', default=None)
    args = ap.parse_args()

    out = {}
    for tag, path in (("before", args.before), ("after", args.after)):
        verts, faces, labels = load(path)
        if labels is None:
            out[tag] = {"patches": {"ALL": patch_stats(verts, faces, labels,
                                                       np.arange(len(faces)))}}
            continue
        uniq = sorted(set(labels))
        d = {}
        for lab in uniq:
            idx = np.nonzero(np.array(labels) == lab)[0]
            d[lab] = patch_stats(verts, faces, labels, idx)
        out[tag] = {"patches": d, "total_area_mm2": sum(v["area_mm2"] for v in d.values())}

    names = sorted(set(out["before"]["patches"]) | set(out["after"]["patches"]))
    print(f"{'patch':22s} {'tris(b/a)':>18s} {'area_mm2(b/a)':>24s} {'dArea%':>8s} {'comp(b/a)':>10s}")
    for lab in names:
        b = out["before"]["patches"].get(lab); a = out["after"]["patches"].get(lab)
        if b is None or a is None:
            print(f"{lab:22s} MISSING in {'after' if b else 'before'}")
            continue
        dA = 100.0 * (a["area_mm2"] - b["area_mm2"]) / b["area_mm2"] if b["area_mm2"] else 0.0
        print(f"{lab:22s} {b['triangles']:8d}/{a['triangles']:<9d} "
              f"{b['area_mm2']:11.3f}/{a['area_mm2']:<11.3f} {dA:+7.2f}% "
              f"{b['components']:4d}/{a['components']:<5d}")
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(out, f, indent=2)


if __name__ == '__main__':
    main()
