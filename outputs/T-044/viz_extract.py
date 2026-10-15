# -*- coding: utf-8 -*-
"""
T-042 · 从 OpenFOAM foamToVTK 真实产物提取速度场并追踪流线

输入：outputs/T-042/vtk/*.vtu / *.vtp（源：WSL /home/lenovo2/patient_cfd/t004_diag，time=400）
输出：outputs/T-042/field.npz（原始点+U+p）、outputs/T-042/viz_data.json（流线+壁面简化的可视化数据）

设计纪律（本项目）：
- 只用真实求解器产物，不合成速度场、不脑补几何；
- 派生量先定量纲：OpenFOAM simpleFoam 的 p 是运动学压力 m^2/s^2，
  Δp(Pa) = rho * p_kin，rho = 1.2 kg/m^3；
- 中间插值方式如实声明（IDW，可视化级，不是二阶守恒插值）。
"""
import json
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
VTK = os.path.join(HERE, "vtk")

DATA_ARRAY_RE = re.compile(r"<DataArray([^>]*)>(.*?)</DataArray>", re.S)


def parse_vtk_arrays(path):
    """返回 {name: (attrs_dict, np.ndarray)}；同名重复出现时以 _2 / _3 后缀区分。"""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    out = {}
    for attrs_raw, body in DATA_ARRAY_RE.findall(text):
        attrs = dict(re.findall(r"(\w+)='([^']*)'", attrs_raw))
        name = attrs.get("Name", "?")
        ncomp = int(attrs.get("NumberOfComponents", 1))
        dtype = attrs.get("type", "Float32")
        arr = np.fromstring(body, dtype=np.float32 if dtype == "Float32" else np.float64, sep=" ")
        if ncomp > 1:
            arr = arr.reshape(-1, ncomp)
        key = name
        i = 2
        while key in out:
            key = f"{name}_{i}"
            i += 1
        out[key] = (attrs, arr)
    return out


def block_arrays(path, section):
    """只解析指定 section（<Points> / <PointData> / <Polys>）内的 DataArray。"""
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


def main():
    print("== 读取内部场 ==", flush=True)
    vol_pts = block_arrays(os.path.join(VTK, "internal.vtu"), "Points")["Points"].astype(np.float64)
    vpd = block_arrays(os.path.join(VTK, "internal.vtu"), "PointData")
    print("内部节点数:", vol_pts.shape, flush=True)
    print("PointData 字段:", {k: v.shape for k, v in vpd.items()}, flush=True)

    U = vpd["U"].astype(np.float64)
    p = vpd["p"].astype(np.float64)

    print("坐标范围 min:", vol_pts.min(axis=0), flush=True)
    print("坐标范围 max:", vol_pts.max(axis=0), flush=True)
    spd = np.linalg.norm(U, axis=1)
    print("速度模长 min/中位/max (m/s):", spd.min(), np.median(spd), spd.max(), flush=True)
    print("p_kin min/max (m^2/s^2):", p.min(), p.max(), flush=True)

    # 边界补丁
    patches = {}
    for nm in ("nostril_L", "nostril_R", "nasopharynx_outlet", "wall"):
        pts = block_arrays(os.path.join(VTK, f"{nm}.vtp"), "Points")["Points"].astype(np.float64)
        polys = block_arrays(os.path.join(VTK, f"{nm}.vtp"), "Polys")
        pd = block_arrays(os.path.join(VTK, f"{nm}.vtp"), "PointData")
        tri = None
        if "connectivity" in polys:
            conn = polys["connectivity"].astype(np.int64)
            tri = conn.reshape(-1, 3)
        patches[nm] = {"pts": pts, "tri": tri, "pointdata": {k: v for k, v in pd.items()}}
        print(f"patch {nm}: 点 {pts.shape}, 三角 {None if tri is None else tri.shape}, "
              f"字段 {[(k, v.shape) for k, v in pd.items()]}", flush=True)

    # 单元拓扑（四节点四面体）
    cells = block_arrays(os.path.join(VTK, "internal.vtu"), "Cells")
    conn = cells.get("connectivity")
    types = cells.get("types")
    n_tet = 0
    if conn is not None and types is not None:
        conn = conn.astype(np.int64)
        utypes = np.unique(types)
        print("单元类型 VTK code 集合:", utypes, flush=True)
        if np.array_equal(utypes, np.array([10.0])):
            conn = conn.reshape(-1, 4)
            n_tet = conn.shape[0]
        print("四面体数:", n_tet, flush=True)

    np.savez_compressed(os.path.join(HERE, "field.npz"),
                        pts=vol_pts, U=U, p=p, conn=conn,
                        wall_pts=patches["wall"]["pts"], wall_tri=patches["wall"]["tri"],
                        nl_pts=patches["nostril_L"]["pts"], nl_tri=patches["nostril_L"]["tri"],
                        nr_pts=patches["nostril_R"]["pts"], nr_tri=patches["nostril_R"]["tri"],
                        out_pts=patches["nasopharynx_outlet"]["pts"],
                        out_tri=patches["nasopharynx_outlet"]["tri"])
    print("已写出 field.npz", flush=True)


if __name__ == "__main__":
    main()
