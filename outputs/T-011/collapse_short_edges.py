# -*- coding: utf-8 -*-
"""T-011 meshing-input step 2 (correct): manifold-preserving collapse of
sub-tolerance edges, one collapse per pass with freshly rebuilt topology.

Why the earlier attempts failed
-------------------------------
1. Blind coordinate weld (coarsen_surface_uniform.py) snapped every vertex onto
   a grid, merging vertices across distinct sheets where the wall folds close to
   itself -> non-manifold junctions. netgen: "TRIG 874 has 5 neighbours",
   "16 wrong oriented neighbourtriangles", endless "Get neighbourpoints failed".
2. A greedy in-pass collapse (first version of this file) reused STALE adjacency
   after each collapse, so the link condition was tested on out-of-date
   neighbourhoods; 244 collapses opened 84 boundary edges (once=84) - holes.

This version rebuilds the full topology (vertex adjacency, edge->triangles,
vertex->triangles) BEFORE every single collapse, so the link condition
N(u) & N(v) == {a, b} is always tested against the current mesh. A collapse that
satisfies it cannot merge across a sheet, so the result stays a closed 2-manifold
(verify: outputs/T-011/inspect_stl.py must report open edges 0, non-manifold 0).

Only edges shorter than `tol` are touched; the ~0.49 mm body of the surface is
left alone, so the three cap areas and the exterior volume barely move.

Usage: python3 collapse_short_edges.py <in.stl> <out.stl> [--tol 0.05]
"""
import argparse
import collections

import numpy as np


def load_ascii_stl(path):
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


def write_ascii_stl(path, tris, name='collapsed'):
    with open(path, 'w') as f:
        f.write('solid %s\n' % name)
        for t in tris:
            u, v = t[1] - t[0], t[2] - t[0]
            n = np.cross(u, v)
            ln = np.linalg.norm(n)
            n = n / ln if ln > 0 else np.zeros(3)
            f.write('  facet normal %.6e %.6e %.6e\n' % tuple(n))
            f.write('    outer loop\n')
            for p in t:
                f.write('      vertex %.6f %.6f %.6f\n' % tuple(p))
            f.write('    endloop\n')
            f.write('  endfacet\n')
        f.write('endsolid %s\n' % name)


def weld_exact(tris):
    """STL soup -> indexed mesh, welding exactly-coincident vertices only."""
    V = tris.reshape(-1, 3)
    key = np.round(V / 1e-9).astype(np.int64)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    return uniq.astype(float) * 1e-9, inv.reshape(-1, 3)


def edge_stats(P, tri):
    e = np.linalg.norm(np.stack([P[tri[:, 1]] - P[tri[:, 0]],
                                 P[tri[:, 2]] - P[tri[:, 1]],
                                 P[tri[:, 0]] - P[tri[:, 2]]], axis=1), axis=2)
    return e.min(), float(np.median(e)), e.max()


def edge_census(tri):
    cnt = collections.Counter()
    for a, b, c in tri:
        for x, y in ((a, b), (b, c), (c, a)):
            cnt[(x, y) if x < y else (y, x)] += 1
    once = sum(1 for v in cnt.values() if v == 1)
    over = sum(1 for v in cnt.values() if v > 2)
    return once, over


def collapse_short(P, tri, tol, cap=2000, verbose=True):
    tri = tri.astype(np.int64).copy()
    alive = np.ones(len(tri), bool)
    ncol = 0
    for it in range(cap):
        idx = np.where(alive)[0]
        adj = collections.defaultdict(set)
        e2t = collections.defaultdict(list)
        v2t = collections.defaultdict(list)
        for i in idx:
            a, b, c = int(tri[i, 0]), int(tri[i, 1]), int(tri[i, 2])
            adj[a].update((b, c)); adj[b].update((a, c)); adj[c].update((a, b))
            v2t[a].append(i); v2t[b].append(i); v2t[c].append(i)
            e2t[(a, b) if a < b else (b, a)].append(i)
            e2t[(b, c) if b < c else (c, b)].append(i)
            e2t[(c, a) if c < a else (a, c)].append(i)

        best = None
        for (u, v), ts in e2t.items():
            if len(ts) != 2:
                continue
            d = float(np.linalg.norm(P[u] - P[v]))
            if d >= tol:
                continue
            t0, t1 = ts
            rest0 = [x for x in tri[t0].tolist() if x != u and x != v]
            rest1 = [x for x in tri[t1].tolist() if x != u and x != v]
            if len(rest0) != 1 or len(rest1) != 1:
                continue
            a, b = rest0[0], rest1[0]
            if (adj[u] & adj[v]) != {a, b}:
                continue
            if best is None or d < best[0]:
                best = (d, u, v)
        if best is None:
            break
        _, u, v = best
        for i in list(v2t[v]):
            if not alive[i]:
                continue
            t = tri[i]
            if v in t:
                tri[i] = np.where(t == v, u, t)
                if tri[i, 0] == tri[i, 1] or tri[i, 1] == tri[i, 2] or tri[i, 0] == tri[i, 2]:
                    alive[i] = False
        ncol += 1
        if verbose and (ncol % 25 == 0):
            print('  collapsed %d  alive %d' % (ncol, int(alive.sum())))

    out = tri[alive]
    used, inv = np.unique(out, return_inverse=True)
    return P[used], inv.reshape(-1, 3), ncol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source')
    ap.add_argument('out')
    ap.add_argument('--tol', type=float, default=0.05)
    ap.add_argument('--cap', type=int, default=2000)
    args = ap.parse_args()

    tris = load_ascii_stl(args.source)
    P, tri = weld_exact(tris)
    e0 = edge_stats(P, tri)
    once0, over0 = edge_census(tri)
    print('in : tris %d verts %d  edge min %.6f median %.4f max %.4f  once %d over %d'
          % (len(tri), len(P), e0[0], e0[1], e0[2], once0, over0))

    P2, tri2, ncol = collapse_short(P, tri, args.tol, args.cap)
    e1 = edge_stats(P2, tri2)
    once1, over1 = edge_census(tri2)
    print('out: tris %d verts %d  edge min %.6f median %.4f max %.4f  once %d over %d  collapsed %d'
          % (len(tri2), len(P2), e1[0], e1[1], e1[2], once1, over1, ncol))

    write_ascii_stl(args.out, P2[tri2])
    print('wrote', args.out)
    if once1 != 0 or over1 != 0:
        print('WARNING: not a clean closed 2-manifold (once=%d over=%d)' % (once1, over1))


if __name__ == '__main__':
    main()
