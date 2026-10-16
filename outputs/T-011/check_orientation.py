"""T-011 diagnostic: is the surface CONSISTENTLY ORIENTED and closed?

Why: netgen reported "File has normal vectors which differ extremely from
geometry->correct with stldoctor", and every size knob (maxh, grading, triangle
count, sliver removal) failed to change its memory blow-up. A sub-2-minute
runaway that ignores size is the signature of a topological/orientation defect,
not of a big model. For a closed, consistently oriented surface every interior
edge is traversed in OPPOSITE directions by its two triangles; this counts the
violations (edges where both triangles traverse it the SAME way = flipped
neighbour) and the boundary edges (used once).

Usage: python3 check_orientation.py <surface.stl>
"""
import sys
import collections

import numpy as np


def load(path):
    tris, cur = [], []
    with open(path, 'r', errors='ignore') as f:
        for line in f:
            s = line.strip()
            if s.startswith('vertex'):
                cur.append([float(x) for x in s.split()[1:4]])
                if len(cur) == 3:
                    tris.append(cur)
                    cur = []
    return np.asarray(tris, dtype=float)


def main(path):
    T = load(path)
    V = T.reshape(-1, 3)
    key = np.round(V / 1e-9).astype(np.int64)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    tri = inv.reshape(-1, 3)

    # directed edge -> count, and undirected edge -> list of directed edges
    directed = collections.Counter()
    undirected = collections.defaultdict(list)
    for a, b, c in tri:
        for x, y in ((a, b), (b, c), (c, a)):
            directed[(x, y)] += 1
            undirected[(x, y) if x < y else (y, x)].append((x, y))

    once = 0
    over = 0
    flipped = 0
    dup_directed = 0
    for e, ds in undirected.items():
        if len(ds) == 1:
            once += 1
        elif len(ds) > 2:
            over += 1
        else:
            d0, d1 = ds
            if d0 == d1:
                flipped += 1          # both triangles traverse the edge the same way
            if directed[d0] > 1 or directed[d1] > 1:
                dup_directed += 1

    print('FILE', path)
    print('  triangles            :', len(tri))
    print('  undirected edges     :', len(undirected))
    print('  boundary edges (once):', once, '   (closed surface must be 0)')
    print('  non-manifold (>2)    :', over)
    print('  FLIPPED neighbours   :', flipped, '   (same-direction traversal; must be 0)')
    print('  duplicate directed   :', dup_directed)


if __name__ == '__main__':
    main(sys.argv[1])
