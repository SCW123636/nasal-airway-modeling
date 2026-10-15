# -*- coding: utf-8 -*-
"""
flow_streamlines · 真实 CFD 场 → 流线追踪 → 单文件三维可视化（工作台自动化组件，T-046）

用途两条路：
1. 命令行/库调用：`build_streamlines(vtk_dir, out_html, out_meta, context)`
   —— vtk_dir 内含 foamToVTK 产物 internal.vtu + nostril_L/nostril_R/nasopharynx_outlet/wall.vtp
2. 工作台钩子：`export_job_streamlines(directory, data, asset, export_root)`
   —— 患者 job 完成后由 cfd_workspace_jobs.run_pressure_job 以 best-effort 调用；
   任何失败只由调用方记录，绝不抛出阻断 job。

口径纪律（不可在本模块放宽）：
- OpenFOAM simpleFoam 的 p 是运动学压力 m^2/s^2，p(Pa) = 1.2 * p_kin（RHO=1.2）。
- 插值 = 定位四面体后按重心坐标线性插值（可视化级，非 cellPoint 反距离加权）；
  定量结论一律以 postProcessing/surfaceFieldValue 为准。
- 本模块不宣称收敛/临床；诚实声明由 context 注入并在页面显著展示。
"""
import base64
import json
import os
import re
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

RHO = 1.2
DS = 0.30e-3
MAX_STEPS = 1200
K_CAND = 16
N_SEED = 60
STALL_SPEED = 3e-3

PATCH_FILES = ("nostril_L", "nostril_R", "nasopharynx_outlet", "wall")
# 出口 patch 名随域口径变化：短域 = nasopharynx_outlet，扩展域 = oropharynx_truncation_outlet。
# 默认保持旧值（短域）→ 旧调用行为零变化；调用方显式传 outlet 走扩展域（T-057 参数化）。
DEFAULT_OUTLET = "nasopharynx_outlet"


def patch_files(outlet=DEFAULT_OUTLET):
    """按出口 patch 名拼出四个必须 patch（鼻孔 L/R + 出口 + 壁面）。"""
    return ("nostril_L", "nostril_R", outlet, "wall")
ASSETS = Path(__file__).resolve().parent / "assets"
THREE_JS_PATH = ASSETS / "three.min.js"
TEMPLATE_PATH = ASSETS / "streamlines_template.html"
APP_JS_PATH = ASSETS / "streamlines_app.js"

DATA_ARRAY_RE = re.compile(r"<DataArray([^>]*)>(.*?)</DataArray>", re.S)


def _patch_path(vtk_dir, name):
    """patch vtp 路径：平铺或 foamToVTK 的 boundary/ 子目录布局。"""
    vtk_dir = Path(vtk_dir)
    for cand in (vtk_dir / (name + ".vtp"), vtk_dir / "boundary" / (name + ".vtp")):
        if cand.is_file():
            return cand
    return vtk_dir / (name + ".vtp")


# ---------------------------------------------------------------- 提取

def block_arrays(path, section):
    """只解析指定 section（<Points> / <PointData> / <Cells> / <Polys>）内的 DataArray。"""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    start = text.find(f"<{section}>")
    end = text.find(f"</{section}>")
    if start < 0 or end < 0:
        return {}
    sub = text[start:end]
    out = {}
    for attrs_raw, body in DATA_ARRAY_RE.findall(sub):
        attrs = dict(re.findall(r"(\w+)='([^']*)'", attrs_raw))
        name = attrs.get("Name", "?")
        ncomp = int(attrs.get("NumberOfComponents", 1))
        arr = np.fromstring(body, dtype=np.float32, sep=" ")
        if ncomp > 1:
            arr = arr.reshape(-1, ncomp)
        out[name] = arr
    return out


def extract_field(vtk_dir, outlet=DEFAULT_OUTLET):
    """vtk_dir: 含 internal.vtu 与四个 patch vtp 的目录。返回 numpy 场 dict。
    outlet: 出口 patch 名（扩展域传 "oropharynx_truncation_outlet"，T-057）。"""
    vtk_dir = Path(vtk_dir)
    internal = vtk_dir / "internal.vtu"
    pts = block_arrays(internal, "Points")["Points"].astype(np.float64)
    vpd = block_arrays(internal, "PointData")
    U = vpd["U"].astype(np.float64)
    p = vpd["p"].astype(np.float64)
    cells = block_arrays(internal, "Cells")
    conn = cells["connectivity"].astype(np.int64)
    types = cells["types"]
    if not np.array_equal(np.unique(types), np.array([10.0])):
        raise ValueError("internal.vtu 含非四面体单元，当前只支持纯 VTK_TETRA")
    conn = conn.reshape(-1, 4)

    field = {"pts": pts, "U": U, "p": p, "conn": conn}
    for nm in patch_files(outlet):
        path = _patch_path(vtk_dir, nm)
        ppts = block_arrays(path, "Points")["Points"].astype(np.float64)
        polys = block_arrays(path, "Polys")
        tri = None
        if "connectivity" in polys:
            tri = polys["connectivity"].astype(np.int64).reshape(-1, 3)
        field[nm + "_pts"] = ppts
        field[nm + "_tri"] = tri
    return field


# ---------------------------------------------------------------- 追踪

def farthest_point_sample(P, n, rng):
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
        self.cc = pts[conn].mean(axis=1)
        self.tree = cKDTree(self.cc)
        self.k_cand = min(K_CAND, len(self.cc))  # 候选数不得超单元总数（小网格防越界）

    def locate(self, q):
        dist, cand = self.tree.query(q[None, :], k=self.k_cand)
        c = self.conn[cand[0]]
        v0 = self.pts[c[:, 0]]
        d1 = self.pts[c[:, 1]] - v0
        d2 = self.pts[c[:, 2]] - v0
        d3 = self.pts[c[:, 3]] - v0
        M = np.stack([d1, d2, d3], axis=2)
        rhs = (q - v0)[:, :, None]
        try:
            x = np.linalg.solve(M, rhs)[:, :, 0]
        except np.linalg.LinAlgError:
            return -1, None
        b3 = 1.0 - x.sum(axis=1)
        bary = np.concatenate([b3[:, None], x], axis=1)
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
        return bary @ self.U[nodes], bary @ self.p[nodes] * RHO


def trace_lines(field, n_seed=N_SEED, ds=DS, max_steps=MAX_STEPS, seed=7,
                outlet=DEFAULT_OUTLET):
    """确定性追踪（固定 rng 种子）：返回 (lines, core_meta)。与 T-044 口径逐位一致。"""
    pts = field["pts"].astype(np.float64)
    conn = field["conn"].astype(np.int64)
    F = Field(pts, conn, field["U"].astype(np.float64), field["p"].astype(np.float64))
    tree_out = cKDTree(field[outlet + "_pts"].astype(np.float64))
    tree_nl = cKDTree(field["nostril_L_pts"].astype(np.float64))
    tree_nr = cKDTree(field["nostril_R_pts"].astype(np.float64))
    rng = np.random.default_rng(seed)

    lines = []
    for side, key, t_in in (("L", "nostril_L_pts", tree_nl), ("R", "nostril_R_pts", tree_nr)):
        patch = field[key].astype(np.float64)
        sel = farthest_point_sample(patch, min(n_seed, len(patch)), rng)
        for si in sel:
            s0 = patch[si]
            Uq, _ = F.sample(s0)
            if Uq is None:
                continue
            nn = np.linalg.norm(Uq)
            if nn < 1e-9:
                continue
            x = s0 + 0.20e-3 * (Uq / nn)
            Uq2, _ = F.sample(x)
            if Uq2 is None:
                x = s0
                Uq2 = Uq
            seed_pt = x.copy()
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

            for _ in range(max_steps):
                k1 = dirf(x)
                if k1 is None:
                    reason = "seed_outside"
                    break
                k2 = dirf(x + 0.5 * ds * k1)
                if k2 is None:
                    k2 = k1
                k3 = dirf(x + 0.5 * ds * k2)
                if k3 is None:
                    k3 = k2
                k4 = dirf(x + ds * k3)
                if k4 is None:
                    k4 = k3
                xn = x + (ds / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
                v, pv = F.sample(xn)
                if v is None:
                    lo, hi = 0.0, 1.0
                    good = x.copy()
                    for _ in range(6):
                        mid = 0.5 * (lo + hi)
                        xm = x + mid * ds * (k1 + 2 * k2 + 2 * k3 + k4) / 6.0
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
                    elif di[0] < 1.2e-3 and np.linalg.norm(good - seed_pt) > 5e-3:
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

    reasons = {}
    for l in lines:
        reasons[l["reason"]] = reasons.get(l["reason"], 0) + 1
    allspd = np.concatenate([l["spd"] for l in lines])
    core = {
        "n_lines": len(lines),
        "n_points_total": int(sum(l["n"] for l in lines)),
        "reasons": reasons,
        "speed_mps": {"min": float(allspd.min()), "median": float(np.median(allspd)),
                      "max": float(allspd.max())},
        "seed": seed, "ds_mm": ds * 1000, "max_steps": max_steps, "n_seed_per_side": n_seed,
    }
    return lines, core


# ---------------------------------------------------------------- vtkStreamTracer 引擎（ParaView 同级）

def trace_lines_vtk(vtk_dir, n_seed=N_SEED, seed=7, max_propagation=0.5,
                    terminal_speed=STALL_SPEED):
    """用 vtkStreamTracer（ParaView 内核）追踪，输出与 trace_lines 同构的 (lines, core)。

    与手写版的对照口径：同种子（farthest_point_sample, rng 同）、同终止归类阈值（1.2 mm）。
    vtk 的积分/插值由其内核决定（默认 RK45 + 求解器同款 cellPoint 类插值），不再复刻手写参数。
    """
    import vtk as _vtk
    from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk

    vtk_dir = Path(vtk_dir)
    reader = _vtk.vtkXMLUnstructuredGridReader()
    reader.SetFileName(str(vtk_dir / "internal.vtu"))
    reader.Update()
    grid = reader.GetOutput()
    grid.GetPointData().SetActiveVectors("U")
    grid.GetPointData().SetActiveScalars("p")

    rng = np.random.default_rng(seed)
    lines = []
    for side, pname in (("L", "nostril_L"), ("R", "nostril_R")):
        pr = _vtk.vtkXMLPolyDataReader()
        pr.SetFileName(str(_patch_path(vtk_dir, pname)))
        pr.Update()
        patch_pts = vtk_to_numpy(pr.GetOutput().GetPoints().GetData()).astype(np.float64)
        sel = farthest_point_sample(patch_pts, min(n_seed, len(patch_pts)), rng)
        seed_pts = patch_pts[sel]

        src = _vtk.vtkPolyData()
        vp = _vtk.vtkPoints()
        vp.SetData(numpy_to_vtk(seed_pts, deep=True))
        src.SetPoints(vp)

        st = _vtk.vtkStreamTracer()
        st.SetInputData(grid)
        st.SetSourceData(src)
        st.SetIntegratorTypeToRungeKutta45()
        st.SetIntegrationDirectionToForward()
        st.SetComputeVorticity(False)
        st.SetMaximumPropagation(max_propagation)
        st.SetTerminalSpeed(terminal_speed)
        st.Update()
        out = st.GetOutput()
        # ReasonForTermination / SeedIds 是 CellData（每条流线一个值）
        reason_arr = out.GetCellData().GetArray("ReasonForTermination")

        # 沿流线探取 U / p（vtkProbeFilter = ParaView 同款探针）
        probe = _vtk.vtkProbeFilter()
        probe.SetInputData(out)
        probe.SetSourceData(grid)
        probe.Update()
        probed = probe.GetOutput()
        pa = probed.GetPointData()
        spd_arr = pa.GetArray("U")
        p_arr = pa.GetArray("p")

        cell = probed.GetLines()
        cell.InitTraversal()
        idlist = _vtk.vtkIdList()
        out_pts = probed.GetPoints()
        cell_i = -1
        while cell.GetNextCell(idlist):
            cell_i += 1
            n = idlist.GetNumberOfIds()
            if n < 4:
                continue
            ids = [idlist.GetId(i) for i in range(n)]
            P = np.array([out_pts.GetPoint(i) for i in ids], dtype=np.float64)
            S = np.array([np.linalg.norm(spd_arr.GetTuple(i)) for i in ids]) if spd_arr else np.zeros(n)
            PP = (np.array([p_arr.GetValue(i) for i in ids]) * RHO) if p_arr else np.zeros(n)
            length = float(np.sum(np.linalg.norm(np.diff(P, axis=0), axis=1)))
            term = int(reason_arr.GetValue(cell_i)) if reason_arr else -1
            lines.append({
                "side": side,
                "vtk_termination": term,   # 1=OUT_OF_DOMAIN 2=NOT_INITIALIZED 3=UNEXPECTED_VALUE 4=OUT_OF_TIME 5=OUT_OF_STEPS 6=STAGNATION
                "reason": None,            # 由 classify 统一归类，口径与手写版一致
                "n": int(n),
                "length_mm": round(length * 1000, 2),
                "seed_mm": None,
                "pts_mm": (P * 1000.0).astype(np.float32),
                "spd": S.astype(np.float32),
                "pPa": PP.astype(np.float32),
            })
    return lines


def classify_endpoints(field, lines, outlet_dist=1.2e-3, inlet_dist=1.2e-3, seed_gap=5e-3,
                       outlet=DEFAULT_OUTLET):
    """按统一口径把终止原因归到 reached_outlet / back_to_inlet / exited_wall_region / stall_near_wall。"""
    tree_out = cKDTree(field[outlet + "_pts"].astype(np.float64))
    tree_in = {"L": cKDTree(field["nostril_L_pts"].astype(np.float64)),
               "R": cKDTree(field["nostril_R_pts"].astype(np.float64))}
    reasons = {}
    for l in lines:
        end = l["pts_mm"][-1].astype(np.float64) / 1000.0
        do, _ = tree_out.query(end[None, :], k=1)
        di, _ = tree_in[l["side"]].query(end[None, :], k=1)
        if l.get("vtk_termination") == 6:
            r = "stall_near_wall"
        elif do[0] < outlet_dist:
            r = "reached_outlet"
        elif di[0] < inlet_dist:
            r = "back_to_inlet"
        else:
            r = "exited_wall_region"
        l["reason"] = r
        reasons[r] = reasons.get(r, 0) + 1
    allspd = np.concatenate([l["spd"] for l in lines]) if lines else np.zeros(1)
    core = {
        "n_lines": len(lines),
        "n_points_total": int(sum(l["n"] for l in lines)),
        "reasons": reasons,
        "speed_mps": {"min": float(allspd.min()), "median": float(np.median(allspd)),
                      "max": float(allspd.max())},
    }
    return core


def build_streamlines_vtk(vtk_dir, out_html, out_meta, context, n_seed=N_SEED, seed=7,
                          outlet=DEFAULT_OUTLET):
    """vtk 引擎版构建：vtkStreamTracer 追踪 + 统一归类 + 同一模板渲染。
    outlet: 扩展域传 "oropharynx_truncation_outlet"（T-057）。"""
    field = extract_field(vtk_dir, outlet=outlet)
    lines = trace_lines_vtk(vtk_dir, n_seed=n_seed, seed=seed)
    core = classify_endpoints(field, lines, outlet=outlet)
    meta = dict(core)
    meta["engine"] = "vtkStreamTracer (ParaView kernel, RK45 + library interpolation)"
    meta["source_vtk_dir"] = str(Path(vtk_dir).resolve())
    meta["rho_for_pressure_Pa"] = RHO
    meta["lines"] = [{k: v for k, v in l.items() if k not in ("pts_mm", "spd", "pPa")}
                     for l in lines]
    html = render_html(field, lines, meta, context, outlet=outlet)
    Path(out_html).write_text(html, encoding="utf-8")
    Path(out_meta).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def minimal_context_for(vtk_dir):
    """无上下文时的最小可用 context（演示/测试用）。"""
    return {
        "title": "三维流线 · 腔内速度与静压",
        "crumb": "鼻腔 CFD 工作台",
        "sub": str(vtk_dir),
        "badges": [("warn", "未收敛"), ("", "未临床复核")],
        "honesty_summary": "未达收敛 · 后处理级流线 · 未经人体复核 · 坐标未归位",
        "honesty": ["该场<b>未达 residualControl 收敛</b>，此图<b>只能用于看流动形态</b>；",
                    "流线由 vtkStreamTracer（ParaView 内核）追踪；定量以 postProcessing 为准；",
                    "未见人体复核：<code>generalisation_test_only_no_human_review</code>；",
                    "坐标尺为求解器坐标（mm），未做 LPS 归位。"],
        "stats": [], "facts": [], "footnote": "vtkStreamTracer 引擎版。",
    }


# ---------------------------------------------------------------- 渲染（工作台 house style）

def _b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def _f32s(a):
    return 'new Float32Array(U8("%s").buffer)' % _b64(a)


def _u32(a):
    return 'new Uint32Array(U8("%s").buffer)' % base64.b64encode(
        np.ascontiguousarray(a).tobytes()).decode("ascii")


def render_html(field, lines, meta, context, outlet=DEFAULT_OUTLET):
    """生成单文件三维流线 HTML。context 注入标题/来源/口径/诚实声明（本模块不编造）。"""
    allpts = np.concatenate([l["pts_mm"] for l in lines] + [field["wall_pts"] * 1000.0])
    bmin, bmax = allpts.min(axis=0), allpts.max(axis=0)
    center = ((bmax + bmin) / 2).tolist()
    radius = float(np.linalg.norm(bmax - bmin) / 2)
    allspd = np.concatenate([l["spd"] for l in lines])
    allp = np.concatenate([l["pPa"] for l in lines])

    def line_js(l):
        return ('{side:%s,reason:%s,length_mm:%s,'
                'pos:new Float32Array(U8("%s").buffer),'
                'spd:new Float32Array(U8("%s").buffer),'
                'p:new Float32Array(U8("%s").buffer)}'
                % (json.dumps(l["side"]), json.dumps(l["reason"]), l["length_mm"],
                   _b64(l["pts_mm"].astype(np.float32)), _b64(l["spd"].astype(np.float32)),
                   _b64(l["pPa"].astype(np.float32))))

    data = ("(function(){function U8(s){const b=atob(s);const u=new Uint8Array(b.length);"
            "for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);return u;}"
            "return {"
            "LINE_DATA:[%s],"
            "WALL_POS:%s, WALL_IDX:%s,"
            "PATCH:{nl_pos:%s,nl_idx:%s,nr_pos:%s,nr_idx:%s,out_pos:%s,out_idx:%s},"
            "META:{spd_p2:%s,spd_max:%s,p_p2:%s,p_max:%s,center:%s,radius:%s,"
            "bbox:{x:[%s,%s],y:[%s,%s],z:[%s,%s]}}};})()"
            % (",".join(line_js(l) for l in lines),
               _f32s((field["wall_pts"] * 1000.0).astype(np.float32).reshape(-1)),
               _u32(field["wall_tri"].astype(np.uint32).reshape(-1)),
               _f32s((field["nostril_L_pts"] * 1000.0).astype(np.float32).reshape(-1)),
               _u32(field["nostril_L_tri"].astype(np.uint32).reshape(-1)),
               _f32s((field["nostril_R_pts"] * 1000.0).astype(np.float32).reshape(-1)),
               _u32(field["nostril_R_tri"].astype(np.uint32).reshape(-1)),
               _f32s((field[outlet + "_pts"] * 1000.0).astype(np.float32).reshape(-1)),
               _u32(field[outlet + "_tri"].astype(np.uint32).reshape(-1)),
               repr(float(np.percentile(allspd, 2))), repr(float(allspd.max())),
               repr(float(np.percentile(allp, 2))), repr(float(allp.max())),
               json.dumps(center), repr(radius),
               repr(round(float(bmin[0]), 1)), repr(round(float(bmax[0]), 1)),
               repr(round(float(bmin[1]), 1)), repr(round(float(bmax[1]), 1)),
               repr(round(float(bmin[2]), 1)), repr(round(float(bmax[2]), 1))))

    n_lines = len(lines)
    n_reach = meta["reasons"].get("reached_outlet", 0)
    pct = round(n_reach / n_lines * 100) if n_lines else 0

    stats = "".join(
        '<div class="stat"><div class="stat-v">%s</div><div class="stat-k">%s</div>%s</div>'
        % (v, k, ('<div class="stat-n">%s</div>' % nt) if nt else "")
        for k, v, nt in context["stats"])
    facts = "".join('<div class="fr"><dt>%s</dt><dd>%s</dd></div>' % (k, v)
                    for k, v in context["facts"])
    honesty = "".join("<li>%s</li>" % h for h in context["honesty"])
    badges = "".join('<span class="badge %s">%s</span>' % (cls, txt)
                     for cls, txt in context["badges"])

    html = (TEMPLATE_PATH.read_text(encoding="utf-8")
                    .replace("__THREEJS__", THREE_JS_PATH.read_text(encoding="utf-8"))
                    .replace("__DATA__", data)
                    .replace("__APP__", APP_JS_PATH.read_text(encoding="utf-8"))
                    .replace("__TITLE__", context["title"])
                    .replace("__CRUMB__", context["crumb"])
                    .replace("__SUB__", context["sub"])
                    .replace("__BADGES__", badges)
                    .replace("__HONESTY__", honesty)
                    .replace("__HONESTY_SUMMARY__", context["honesty_summary"])
                    .replace("__STATS__", stats).replace("__FACTS__", facts)
                    .replace("__NLINES__", str(n_lines))
                    .replace("__NREACH__", str(n_reach)).replace("__PCT__", str(pct))
                    .replace("__FOOTNOTE__", context["footnote"]))
    return html


def build_streamlines(vtk_dir, out_html, out_meta, context):
    """提取 → 追踪 → 渲染。返回 meta（含 core + context 溯源）。"""
    field = extract_field(vtk_dir)
    lines, core = trace_lines(field)
    meta = dict(core)
    meta["source_vtk_dir"] = str(Path(vtk_dir).resolve())
    meta["interpolation"] = "linear barycentric inside located tetrahedron (visualisation grade)"
    meta["rho_for_pressure_Pa"] = RHO
    meta["lines"] = [{k: v for k, v in l.items() if k not in ("pts_mm", "spd", "pPa")}
                     for l in lines]
    html = render_html(field, lines, meta, context)
    Path(out_html).write_text(html, encoding="utf-8")
    Path(out_meta).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


# ---------------------------------------------------------------- 工作台钩子

def export_job_streamlines(directory, data, asset, export_root):
    """cfd_workspace_jobs 患者分支的 best-effort 后处理。
    返回 status dict；缺输入时返回原因而不抛错（由调用方决定记录方式）。"""
    vtus = sorted(Path(export_root).rglob("internal.vtu"),
                  key=lambda p: p.stat().st_mtime)
    if not vtus:
        return {"status": "no_vtu"}
    vtu = vtus[-1]
    vtk_dir = vtu.parent
    missing = [n for n in PATCH_FILES if not _patch_path(vtk_dir, n).is_file()]
    if missing:
        return {"status": "missing_patches", "missing": missing, "vtk_dir": str(vtk_dir)}

    result = data.get("result") or {}
    validation = result.get("numerical_validation", "unchecked")
    out_html = Path(directory) / "streamlines.html"
    out_meta = Path(directory) / "streamlines_meta.json"
    context = job_context(data, vtu, validation)
    meta = build_streamlines(vtk_dir, out_html, out_meta, context)
    asset("streamlines.html", out_html, "三维流线可视化（腔内速度 / 静压）")
    asset("streamlines_meta.json", out_meta, "流线追踪记录（种子 / 终止原因 / 口径）")
    return {"status": "generated", "n_lines": meta["n_lines"],
            "reached_outlet": meta["reasons"].get("reached_outlet", 0),
            "source_vtu": str(vtu)}


def job_context(data, vtu, validation):
    """从 job 数据组装页面 context；只搬运真实字段，不补造数字。"""
    case = data.get("case_id", "?")
    job = data.get("id", "?")
    result = data.get("result") or {}
    stats = []
    scenarios = result.get("scenarios") or {}
    for sc in scenarios.values():
        solved = sc.get("result") or {}
        if solved.get("pressure_pa") is not None:
            stats.append(("共同入口静压", "%.2f Pa" % solved["pressure_pa"], "surfaceFieldValue"))
        q = solved.get("q_total_m3_s")
        if q is not None:
            stats.append(("实测总流量", "%.1f L/min" % (q * 60000.0), ""))
        break
    facts = [("来源", "job <code>%s</code> · 病例 <code>%s</code>" % (job, case)),
             ("场文件", "<code>%s</code>" % vtu.name),
             ("收敛状态", "数值验证：<code>%s</code>" % validation),
             ("临床状态", "<code>generalisation_test_only_no_human_review</code>")]
    return {
        "title": "三维流线 · 腔内速度与静压",
        "crumb": "鼻腔 CFD 工作台 · 患者工程试算 <b>%s</b>" % job,
        "sub": "病例 %s · 场文件 %s（foamToVTK 导出）" % (case, vtu.name),
        "badges": [("warn", "未收敛" if validation != "passed_engineering_screen" else "工程屏通过"),
                   ("", "未临床复核")],
        "honesty_summary": "未达 residualControl 收敛 · 可视化级插值 · 未经人体复核 · 坐标未归位",
        "honesty": [
            "该场<b>未达 residualControl 收敛</b>（<code>numerical_validation: %s</code>），"
            "Δp 稳态等业务判据不成立，此图<b>只能用于看流动形态，不能用于临床结论</b>；" % validation,
            "插值为「定位四面体后按重心坐标线性插值」，<b>可视化级</b>；"
            "定量一律以 postProcessing 的 <code>surfaceFieldValue</code> 为准；",
            "未见人体复核：<code>clinical_status: generalisation_test_only_no_human_review</code>；",
            "坐标尺为<b>求解器坐标</b>（mm），未做 LPS/解剖方位归位，x/y/z 不等于「左右/前后/上下」。",
        ],
        "stats": stats,
        "facts": facts,
        "footnote": "流线追踪：RK4 单位速度场积分，步长 0.30 mm；种子取两侧鼻孔面各 60 个（最远点采样）。"
                    "本页由 job 完成后自动生成（T-046）。",
    }
