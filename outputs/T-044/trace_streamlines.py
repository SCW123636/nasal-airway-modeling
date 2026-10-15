# -*- coding: utf-8 -*-
"""
T-042 · 真实 CFD 场上的流线追踪（四面体内线性插值版）

源场：outputs/T-042/field.npz
  来自 WSL /home/lenovo2/patient_cfd/t004_diag（网格 b15_patient_maxh1_repaired.msh）
  time index = 400，foamToVTK 导出的真实节点场 PointData{p, U} + 四面体拓扑。

插值：定位点所在四面体后，用 4 个顶点上的 U / p 做**线性（重心坐标）插值**。
     等价于 P1 有限元场的精确取值，不是 IDW 近似；
     仍不等于 OpenFOAM `interpolationScheme cellPoint`（后者为反距离加权），
     因此本脚本产出只用于可视化；定量结论一律以 postProcessing/surfaceFieldValue 为准。
积分：单位速度场 RK4，几何步长 0.30 mm。
"""
import json
import os

import numpy as np
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
RHO = 1.2
DS = 0.30e-3
MAX_STEPS = 1200
K_CAND = 16
N_SEED = 60
STALL_SPEED = 3e-3
RNG = np.random.default_rng(7)


def farthest_point_sample(P, n, rng):
    """在补丁节点里做最远点采样 → 面上分布均匀"""
    idx = [int(rng.integers(len(P)))]
    d = np.linalg.norm(P - P[idx[0]], axis=1)
    for _ in range(n - 1):
        nxt = int(np.argmax(d))
        idx.append(nxt)
        d = np.minimum(d, np.linalg.norm(P - P[nxt], axis=1))
    return np.array(idx)


class Field:
    def __init__(self, pts, conn, U, p):
        self.pts = pts
        self.conn = conn
        self.U = U
        self.p = p
        V = pts[conn]                       # (M,4,3)
        self.V = V
        self.cc = V.mean(axis=1)            # (M,3)
        print(f"  建立四面体中心 KD-tree（{len(self.cc)} 单元）...", flush=True)
        self.tree = cKDTree(self.cc)

    def locate(self, q):
        """返回 (cell_index or -1, bary(4,) or None)"""
        dist, cand = self.tree.query(q[None, :], k=K_CAND)
        c = self.conn[cand[0]]              # (K,4)
        v0 = self.pts[c[:, 0]]
        d1 = self.pts[c[:, 1]] - v0
        d2 = self.pts[c[:, 2]] - v0
        d3 = self.pts[c[:, 3]] - v0
        M = np.stack([d1, d2, d3], axis=2)  # (K,3,3) 列 = d1 d2 d3
        rhs = (q - v0)[:, :, None]
        try:
            x = np.linalg.solve(M, rhs)[:, :, 0]   # (K,3)
        except np.linalg.LinAlgError:
            return -1, None
        b3 = 1.0 - x.sum(axis=1)
        bary = np.concatenate([b3[:, None], x], axis=1)   # (K,4)
        ok = bary.min(axis=1) >= -1e-7
        if not ok.any():
            return -1, None
        k = int(np.argmax(bary.min(axis=1)))
        return int(cand[0][k]), bary[k]

    def sample(self, q):
        ci, bary = self.locate(q)
        if ci < 0:
            return None, None
        nodes = self.conn[ci]
        Uq = bary @ self.U[nodes]
        pq = bary @ self.p[nodes]
        return Uq, pq * RHO


def main():
    d = np.load(os.path.join(HERE, "field.npz"))
    pts = d["pts"].astype(np.float64)
    conn = d["conn"].astype(np.int64)
    U = d["U"].astype(np.float64)
    p = d["p"].astype(np.float64)
    print("载入场：", pts.shape, conn.shape, flush=True)
    F = Field(pts, conn, U, p)
    tree_out = cKDTree(d["out_pts"].astype(np.float64))
    tree_nl = cKDTree(d["nl_pts"].astype(np.float64))
    tree_nr = cKDTree(d["nr_pts"].astype(np.float64))

    lines = []
    for side, key, t_in in (("L", "nl_pts", tree_nl), ("R", "nr_pts", tree_nr)):
        patch = d[key].astype(np.float64)
        sel = farthest_point_sample(patch, min(N_SEED, len(patch)), RNG)
        n_ok = 0
        for si in sel:
            s0 = patch[si]
            # 起点沿进口速度方向内移 0.20 mm
            Uq, pq = F.sample(s0)
            if Uq is None:
                continue
            nn = np.linalg.norm(Uq)
            if nn < 1e-9:
                continue
            seed = s0 + 0.20e-3 * (Uq / nn)
            Uq2, _ = F.sample(seed)
            if Uq2 is None:
                seed = s0
                Uq2 = Uq
            x = seed.copy()
            P = [x.copy()]
            S = [float(np.linalg.norm(Uq2))]
            PP = [float(F.sample(x)[1])]
            reason = "maxlen"
            stall = 0

            def dirf(q):
                v, _ = F.sample(q)
                if v is None:
                    return None
                n = np.linalg.norm(v)
                if n < 1e-12:
                    return np.zeros(3)
                return v / n

            for _ in range(MAX_STEPS):
                k1 = dirf(x)
                if k1 is None:
                    reason = "seed_outside"
                    break
                k2 = dirf(x + 0.5 * DS * k1)
                if k2 is None:
                    k2 = k1
                k3 = dirf(x + 0.5 * DS * k2)
                if k3 is None:
                    k3 = k2
                k4 = dirf(x + DS * k3)
                if k4 is None:
                    k4 = k3
                xn = x + (DS / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
                v, pv = F.sample(xn)
                if v is None:
                    # 二分回退到边界内的最后一点（最多 6 次）
                    lo, hi = 0.0, 1.0
                    good = x.copy()
                    for _ in range(6):
                        mid = 0.5 * (lo + hi)
                        xm = x + mid * DS * (k1 + 2 * k2 + 2 * k3 + k4) / 6.0
                        if F.sample(xm)[0] is not None:
                            good = xm
                            lo = mid
                        else:
                            hi = mid
                    P.append(good)
                    vg, pvg = F.sample(good)
                    S.append(float(np.linalg.norm(vg)))
                    PP.append(float(pvg))
                    do, _ = tree_out.query(good[None, :], k=1)
                    di, _ = t_in.query(good[None, :], k=1)
                    if do[0] < 1.2e-3:
                        reason = "reached_outlet"
                    elif di[0] < 1.2e-3 and np.linalg.norm(good - seed) > 5e-3:
                        reason = "back_to_inlet"
                    else:
                        reason = "exited_wall_region"
                    break
                sp = float(np.linalg.norm(v))
                if sp < STALL_SPEED:
                    stall += 1
                    if stall >= 4:
                        reason = "stall_near_wall"
                        P.append(xn)
                        S.append(sp)
                        PP.append(float(pv))
                        break
                else:
                    stall = 0
                P.append(xn)
                S.append(sp)
                PP.append(float(pv))
                x = xn
            Pa = np.asarray(P, dtype=np.float64)
            if len(Pa) < 4:
                continue
            length = float(np.sum(np.linalg.norm(np.diff(Pa, axis=0), axis=1)))
            lines.append({
                "side": side,
                "reason": reason,
                "n": int(len(Pa)),
                "length_mm": round(length * 1000, 2),
                "seed_mm": [round(float(v) * 1000, 3) for v in s0],
                "pts_mm": (Pa * 1000.0).astype(np.float32),
                "spd": np.asarray(S, dtype=np.float32),
                "pPa": np.asarray(PP, dtype=np.float32),
            })
            n_ok += 1
        print(f"侧 {side}: {n_ok} 条流线", flush=True)

    reasons = {}
    for l in lines:
        reasons[l["reason"]] = reasons.get(l["reason"], 0) + 1
    n_pts = int(sum(l["n"] for l in lines))
    allspd = np.concatenate([l["spd"] for l in lines])
    print("终止原因:", reasons, flush=True)
    print(f"合计 {len(lines)} 条 / {n_pts} 点；速度 min {allspd.min():.4f} 中位 {np.median(allspd):.4f} max {allspd.max():.4f} m/s", flush=True)

    np.savez_compressed(os.path.join(HERE, "streamlines.npz"),
                        **{f"line_{i:03d}": l["pts_mm"] for i, l in enumerate(lines)},
                        **{f"spd_{i:03d}": l["spd"] for i, l in enumerate(lines)},
                        **{f"pPa_{i:03d}": l["pPa"] for i, l in enumerate(lines)})
    lines_meta = [{k: v for k, v in l.items() if k not in ("pts_mm", "spd", "pPa")} for l in lines]
    meta = {
        "source_case": "/home/lenovo2/patient_cfd/t004_diag",
        "source_time_index": 400,
        "derived_from": "foamToVTK -latestTime -ascii -fields (p U) → internal.vtu (PointData p,U + tetra connectivity)",
        "interpolation": "linear barycentric inside located tetrahedron from the 4 nodal values",
        "integration": f"RK4 on unit velocity field, ds={DS*1000} mm, MAX_STEPS={MAX_STEPS}",
        "rho_for_pressure_Pa": RHO,
        "candidate_cells_K": K_CAND,
        "n_lines": len(lines),
        "n_points_total": n_pts,
        "reasons": reasons,
        "speed_mps": {"min": float(allspd.min()), "median": float(np.median(allspd)), "max": float(allspd.max())},
        "lines": lines_meta,
    }
    with open(os.path.join(HERE, "trace_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("写出 streamlines.npz / trace_meta.json", flush=True)


if __name__ == "__main__":
    main()
