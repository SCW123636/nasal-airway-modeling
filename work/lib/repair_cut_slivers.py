# -*- coding: utf-8 -*-
"""
Repair cut-region sliver geometry (short edges / collapsed triangles) on a partitioned
surface STL, by iterative short-edge collapse with the link condition.

Why: the cut operation produced ~0.0003 mm edges and quality ~6e-7 triangles. Those
slivers are what make (a) native surfaceCheck report phantom self-intersection hits and
(b) checkMesh fail minEdgeLength / minQuality. Collapsing them fixes both at once.

Keeps each triangle's patch (region) assignment, keeps the surface closed and manifold,
and writes ASCII STL with `solid <region>` blocks identical in structure to the input
so the same native surfaceCheck command can re-validate it.
"""
import numpy as np, json, math, argparse, sys


# ---------------------------------------------------------------- parse
def parse_stl_regions(path):
    regions, tris = [], []
    cur_region, cur = None, []
    with open(path, 'r', errors='ignore') as f:
        for line in f:
            s = line.strip()
            if s.startswith('solid'):
                parts = s.split(None, 1)
                cur_region = parts[1] if len(parts) > 1 else 'region'
            elif s.startswith('facet normal'):
                cur = []
            elif s.startswith('vertex'):
                p = s.split()
                cur.append((float(p[1]), float(p[2]), float(p[3])))
                if len(cur) == 3:
                    tris.append(cur); regions.append(cur_region)
    return np.array(tris, dtype=np.float64), regions


def build_topology(tris, tol=1e-9):
    # NOTE: `inv` from np.unique is aligned to the SORTED unique order, and
    # first_idx[i] is the first occurrence of uniq_keys[i]. So verts MUST be
    # flat[first_idx] with NO reordering, otherwise faces index into a permuted
    # vertex array -> combinatorics survive but geometry is scrambled.
    flat = tris.reshape(-1, 3)
    key = np.round(flat / tol).astype(np.int64)
    _, first_idx = np.unique(key, axis=0, return_index=True)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    verts = flat[first_idx]
    faces = inv.reshape(-1, 3)
    return verts, faces


def sanity_check(verts, faces, name=""):
    """Guard against vertex/face misalignment: median edge must be mesh-scale sane."""
    a = verts[faces[:, 0]]; b = verts[faces[:, 1]]; c = verts[faces[:, 2]]
    e0 = np.linalg.norm(b - a, axis=1)
    e1 = np.linalg.norm(c - b, axis=1)
    e2 = np.linalg.norm(a - c, axis=1)
    med = float(np.median(np.concatenate([e0, e1, e2])))
    mx = float(np.max(np.concatenate([e0, e1, e2])))
    ok = med < 5e-3 and mx < 5e-2   # median < 5 mm, max < 50 mm (airway scale)
    print(f"[sanity{':' + name if name else ''}] median_edge={med*1e3:.4f} mm "
          f"max_edge={mx*1e3:.4f} mm -> {'OK' if ok else 'FAIL (geometry scrambled?)'}")
    return ok


# ---------------------------------------------------------------- metrics
def edge_len(verts, a, b):
    return float(np.linalg.norm(verts[a] - verts[b]))


def tri_quality(verts, f):
    p0, p1, p2 = verts[f[0]], verts[f[1]], verts[f[2]]
    l1 = np.linalg.norm(p1 - p0); l2 = np.linalg.norm(p2 - p1); l3 = np.linalg.norm(p0 - p2)
    a = np.cross(p1 - p0, p2 - p0)
    area = 0.5 * float(np.linalg.norm(a))
    denom = l1 * l1 + l2 * l2 + l3 * l3
    if denom <= 0:
        return 0.0
    return 4.0 * math.sqrt(3.0) * area / denom


def mesh_stats(verts, faces):
    mn_e, mn_q = float('inf'), float('inf')
    for f in faces:
        for k in range(3):
            mn_e = min(mn_e, edge_len(verts, f[k], f[(k + 1) % 3]))
        mn_q = min(mn_q, tri_quality(verts, f))
    return mn_e, mn_q


def topology_report(verts, faces):
    ef = {}
    for fi, fc in enumerate(faces):
        for k in range(3):
            a, b = int(fc[k]), int(fc[(k + 1) % 3])
            e = (a, b) if a < b else (b, a)
            ef.setdefault(e, []).append(fi)
    counts = {}
    for e, fl in ef.items():
        counts[len(fl)] = counts.get(len(fl), 0) + 1
    return counts, ef


# ---------------------------------------------------------------- collapse
class Mesh:
    def __init__(self, verts, faces, regions):
        self.verts = [np.asarray(v, dtype=np.float64) for v in verts]
        self.faces = [list(map(int, f)) for f in faces]
        self.regions = list(regions)
        self.alive_f = [True] * len(self.faces)
        self.alive_v = [True] * len(self.verts)
        self.ef = {}
        self.vf = [set() for _ in self.verts]
        for fi, fc in enumerate(self.faces):
            for k in range(3):
                a, b = int(fc[k]), int(fc[(k + 1) % 3])
                e = (a, b) if a < b else (b, a)
                self.ef.setdefault(e, []).append(fi)
            for v in fc:
                self.vf[int(v)].add(fi)

    def _third(self, f, a, b):
        s = set(int(v) for v in self.faces[f])
        s.difference_update({a, b})
        if len(s) != 1:
            return None
        return s.pop()

    def try_collapse(self, a, b):
        if not (self.alive_v[a] and self.alive_v[b]):
            return False
        key = (a, b) if a < b else (b, a)
        fl = [f for f in self.ef.get(key, []) if self.alive_f[f]]
        if len(fl) != 2:
            return False
        f1, f2 = fl[0], fl[1]
        c = self._third(f1, a, b)
        d = self._third(f2, a, b)
        if c is None or d is None:
            return False
        na, nb = set(), set()
        for f in self.vf[a]:
            if self.alive_f[f]:
                na.update(int(v) for v in self.faces[f])
        for f in self.vf[b]:
            if self.alive_f[f]:
                nb.update(int(v) for v in self.faces[f])
        na.discard(a); na.discard(b)
        nb.discard(a); nb.discard(b)
        if (na & nb) != {c, d}:
            return False  # link condition violated -> would create non-manifold
        affected = set(f for f in self.vf[a] if self.alive_f[f])
        affected |= set(f for f in self.vf[b] if self.alive_f[f])
        # detach edges of affected faces
        for f in affected:
            fc = self.faces[f]
            for k in range(3):
                x, y = int(fc[k]), int(fc[(k + 1) % 3])
                e = (x, y) if x < y else (y, x)
                if e in self.ef and f in self.ef[e]:
                    self.ef[e].remove(f)
                    if not self.ef[e]:
                        del self.ef[e]
        for f in (f1, f2):
            self.alive_f[f] = False
        for f in affected:
            if not self.alive_f[f]:
                continue
            self.faces[f] = [a if int(v) == b else int(v) for v in self.faces[f]]
        self.verts[a] = (self.verts[a] + self.verts[b]) / 2.0
        self.vf[a] = set(f for f in (self.vf[a] | self.vf[b]) if self.alive_f[f])
        self.vf[b] = set()
        self.alive_v[b] = False
        for f in affected:
            if not self.alive_f[f]:
                continue
            fc = self.faces[f]
            for k in range(3):
                x, y = int(fc[k]), int(fc[(k + 1) % 3])
                e = (x, y) if x < y else (y, x)
                self.ef.setdefault(e, []).append(f)
        return True

    def collapse_short_edges(self, eps_len, max_passes=50):
        total = 0
        for _ in range(max_passes):
            changed = 0
            for e in list(self.ef.keys()):
                a, b = e
                if not (self.alive_v[a] and self.alive_v[b]):
                    continue
                if np.linalg.norm(self.verts[a] - self.verts[b]) < eps_len:
                    if self.try_collapse(a, b):
                        changed += 1
            total += changed
            if changed == 0:
                break
        return total

    def collapse_low_quality(self, qmin, max_passes=50):
        total = 0
        for _ in range(max_passes):
            changed = 0
            for fi in range(len(self.faces)):
                if not self.alive_f[fi]:
                    continue
                f = self.faces[fi]
                if tri_quality(self.verts, f) >= qmin:
                    continue
                best, bl = None, float('inf')
                for k in range(3):
                    a, b = int(f[k]), int(f[(k + 1) % 3])
                    L = np.linalg.norm(self.verts[a] - self.verts[b])
                    if L < bl:
                        bl, best = L, (a, b)
                if best and self.try_collapse(best[0], best[1]):
                    changed += 1
            total += changed
            if changed == 0:
                break
        return total

    def compact(self):
        vmap = {}
        newv = []
        for i in range(len(self.verts)):
            if self.alive_v[i]:
                vmap[i] = len(newv)
                newv.append(self.verts[i])
        newf, newr = [], []
        for fi in range(len(self.faces)):
            if self.alive_f[fi]:
                newf.append([vmap[int(v)] for v in self.faces[fi]])
                newr.append(self.regions[fi])
        return np.array(newv, dtype=np.float64), np.array(newf, dtype=np.int64), newr


# ---------------------------------------------------------------- write
def write_stl_regions(path, verts, faces, regions, order):
    groups = {}
    for fi, r in enumerate(regions):
        groups.setdefault(r, []).append(fi)
    names = [n for n in order if n in groups] + [n for n in groups if n not in order]
    with open(path, 'w', encoding='utf-8') as f:
        for name in names:
            f.write(f"solid {name}\n")
            for fi in groups[name]:
                p0, p1, p2 = verts[faces[fi][0]], verts[faces[fi][1]], verts[faces[fi][2]]
                n = np.cross(p1 - p0, p2 - p0)
                ln = np.linalg.norm(n)
                if ln > 0:
                    n = n / ln
                f.write(f" facet normal {n[0]:.17g} {n[1]:.17g} {n[2]:.17g}\n")
                f.write("  outer loop\n")
                for p in (p0, p1, p2):
                    f.write(f"   vertex {p[0]:.17g} {p[1]:.17g} {p[2]:.17g}\n")
                f.write("  endloop\n")
                f.write(" endfacet\n")
            f.write(f"endsolid {name}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stl', required=True)
    ap.add_argument('--eps-mm', type=float, default=0.05)
    ap.add_argument('--qmin', type=float, default=0.0)
    ap.add_argument('--out', required=True)
    ap.add_argument('--report', default=None)
    args = ap.parse_args()

    tris, regions = parse_stl_regions(args.stl)
    verts, faces = build_topology(tris)
    if not sanity_check(verts, faces, name="input"):
        print("[ABORT] input topology sanity failed; refusing to repair")
        sys.exit(2)
    order = []
    for r in regions:
        if r not in order:
            order.append(r)
    print(f"[in ] {len(faces)} tris, {len(verts)} verts, regions={order}")

    cnt, _ = topology_report(verts, faces)
    mn_e, mn_q = mesh_stats(verts, faces)
    print(f"[before] edge-counts={cnt} min_edge={mn_e:.6e} m  min_quality={mn_q:.6e}")

    m = Mesh(verts, faces, regions)
    n1 = m.collapse_short_edges(args.eps_mm * 1e-3)
    print(f"[collapse-short] collapsed {n1} edges (eps={args.eps_mm} mm)")
    n2 = 0
    if args.qmin > 0:
        n2 = m.collapse_low_quality(args.qmin)
        print(f"[collapse-quality] collapsed {n2} edges (qmin={args.qmin})")

    nv, nf, nr = m.compact()
    if not sanity_check(nv, nf, name="repaired"):
        print("[ABORT] repaired topology sanity failed; refusing to write")
        sys.exit(3)
    cnt2, _ = topology_report(nv, nf)
    mn_e2, mn_q2 = mesh_stats(nv, nf)
    print(f"[after ] {len(nf)} tris, {len(nv)} verts, edge-counts={cnt2}")
    print(f"[after ] min_edge={mn_e2:.6e} m  min_quality={mn_q2:.6e}")

    write_stl_regions(args.out, nv, nf, nr, order)
    print(f"[out] wrote {args.out}")

    rep = {
        "input": args.stl,
        "output": args.out,
        "eps_mm": args.eps_mm,
        "qmin": args.qmin,
        "before": {"triangles": int(len(faces)), "vertices": int(len(verts)),
                   "edge_face_counts": cnt, "min_edge_m": mn_e, "min_quality": mn_q},
        "after": {"triangles": int(len(nf)), "vertices": int(len(nv)),
                  "edge_face_counts": cnt2, "min_edge_m": mn_e2, "min_quality": mn_q2},
        "collapsed_short": int(n1),
        "collapsed_quality": int(n2),
        "patches_after": {r: nr.count(r) for r in order},
    }
    print(json.dumps(rep, indent=2))
    if args.report:
        with open(args.report, 'w', encoding='utf-8') as f:
            json.dump(rep, f, indent=2)


if __name__ == '__main__':
    main()
