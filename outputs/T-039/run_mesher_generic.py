"""T-039/G: run SlicerVMTK's `CFD Mesh Generator` headless on an arbitrary STL.

Generalisation of run_cfd_mesher.py: takes any STL (binary or ASCII), scales it into
millimetres for Slicer/VMTK, meshes it with the chosen engine and an optional prismatic
boundary layer, and writes the volume mesh + a run report.

Called from Slicer:
    Slicer.exe --no-splash --no-main-window --testing --python-script <this>

Job parameters are read from the JSON file named by the environment variable
T039_JOB (so the same script serves several geometries without edits).
"""
import json
import os
import struct
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

import numpy as np
import slicer
import vtk

LOG = []


def say(text):
    print(text, flush=True)
    LOG.append(str(text))


# ---------------------------------------------------------------------------
# STL readers
# ---------------------------------------------------------------------------

def read_stl(path):
    """(vertices_mm, triangles) with merged points, plus per-triangle solid names.

    Handles binary and ASCII STL. Returns (points Nx3 float64, faces Mx3 int32,
    names list of M strings or None).
    """
    raw = path.read_bytes()
    head = raw[:5].lower()
    if head == b"solid" and b"facet" in raw[:2000].lower():
        return _read_ascii(raw)
    return _read_binary(raw)


def _read_binary(raw):
    n = struct.unpack("<I", raw[80:84])[0]
    dt = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    tri = np.frombuffer(raw[84:84 + 50 * n], dtype=dt)["v"].reshape(-1, 3, 3)
    return _merge(tri.astype(np.float64))


def _read_ascii(raw):
    tris, names = [], []
    name = None
    cur = []
    for line in raw.decode("ascii", "replace").splitlines():
        s = line.strip()
        if s.startswith("solid "):
            name = s[6:].strip()
        elif s.startswith("endsolid"):
            name = None
        elif s.startswith("vertex "):
            cur.append(tuple(float(v) for v in s.split()[1:4]))
            if len(cur) == 3:
                tris.append(cur)
                names.append(name)
                cur = []
    return _merge(np.asarray(tris, dtype=np.float64)) + (names,)


def _merge(tri):
    flat = tri.reshape(-1, 3)
    uniq, inv = np.unique(flat, axis=0, return_inverse=True)
    return uniq, inv.reshape(-1, 3).astype(np.int32), None


def build_polydata(points, faces, ids_per_face=None):
    pts = vtk.vtkPoints()
    pts.SetData(vtk.util.numpy_support.numpy_to_vtk(points.astype(np.float64), deep=True))
    ca = vtk.vtkCellArray()
    for f in faces:
        ca.InsertNextCell(3)
        for v in f:
            ca.InsertCellPoint(int(v))
    pd = vtk.vtkPolyData()
    pd.SetPoints(pts)
    pd.SetPolys(ca)
    if ids_per_face is not None:
        arr = vtk.util.numpy_support.numpy_to_vtk(
            np.ascontiguousarray(ids_per_face.astype(np.int32)), deep=True)
        arr.SetName("CellEntityIds")
        pd.GetCellData().AddArray(arr)
    return pd


# ---------------------------------------------------------------------------

def main():
    raw_job = os.environ["T039_JOB"]
    job = (json.loads(Path(raw_job).read_text(encoding="utf-8"))
           if Path(raw_job).is_file() else json.loads(raw_job))
    stl = Path(job["stl"])
    outdir = Path(job["out"])
    outdir.mkdir(parents=True, exist_ok=True)
    unit_scale = float(job.get("unit_scale", 1.0))     # -> millimetres
    target_edge = float(job.get("target_edge_mm", 1.0))

    report = {"schema": "t039_mesher_run/v1", "job": job, "steps": LOG}

    points, faces, names = read_stl(stl)
    points = points * unit_scale
    say("STL %s -> %d points, %d triangles (unit_scale=%g)" % (stl.name, len(points), len(faces), unit_scale))
    lo, hi = points.min(0), points.max(0)
    say("bbox mm %s -> %s" % (np.round(lo, 3).tolist(), np.round(hi, 3).tolist()))

    ids = None
    if names is not None:
        order = []
        for nm in names:
            if nm not in order:
                order.append(nm)
        # wall first so it takes id 1 (MeshingPipeline.wallCellEntityId); caps above it
        order = sorted(order, key=lambda x: (x != "wall", x))
        mapping = {nm: i + 1 for i, nm in enumerate(order)}
        ids = np.array([mapping[nm] for nm in names], dtype=np.int64)
        say("ASCII solids -> ids %s" % mapping)
    else:
        # Binary STL carries no face ids: put the wall (id 1) on every face and let the
        # pipeline see no caps. It is a closed surface, so there is nothing to cap.
        ids = np.ones(len(faces), dtype=np.int64)
        say("binary STL -> single wall id 1 on all %d faces" % len(faces))

    pd = build_polydata(points, faces, ids)
    report["surface"] = {"points": int(len(points)), "triangles": int(len(faces)),
                         "bbox_mm": [lo.round(4).tolist(), hi.round(4).tolist()],
                         "unit_scale": unit_scale,
                         "id_histogram": {str(k): int(v) for k, v in
                                          sorted(Counter(ids.tolist()).items())}}

    # --- module + path fixups ------------------------------------------------
    ext_root = r"D:\项目\鼻腔建模\软件\slicer\3D Slicer 5.12.4\slicer.org\Extensions-34645"
    for ext in ("SlicerVMTK", "ExtraMarkups"):
        for sub in ("qt-scripted-modules", "qt-loadable-modules",
                    os.path.join("qt-loadable-modules", "Python")):
            p = os.path.join(ext_root, ext, "lib", "Slicer-5.12", sub)
            if os.path.isdir(p):
                if p not in sys.path:
                    sys.path.insert(0, p)
                try:
                    os.add_dll_directory(p)
                except Exception:
                    pass
    import vtkvmtkMiscPython  # noqa: F401
    import CfdMeshGenerator as CMG
    from CfdMeshGeneratorLib import MeshingPipeline as MP
    from CfdMeshGeneratorLib import Netgen as NetgenLib

    logic = CMG.CfdMeshGeneratorLogic()
    use_netgen = job.get("mesher", "netgen") == "netgen" and logic.isNetgenAvailable()
    if job.get("mesher", "netgen") == "netgen" and not logic.isNetgenAvailable():
        say("netgen unavailable (%s) -> falling back to TetGen" % NetgenLib.REQUIREMENT)
    say("mesher availability: tetgen=%s netgen=%s -> using %s"
        % (MP.MeshingPipeline.isTetGenAvailable(), MP.MeshingPipeline.isNetgenAvailable(),
           "netgen" if use_netgen else "tetgen"))
    report["mesher_availability"] = {"tetgen": bool(MP.MeshingPipeline.isTetGenAvailable()),
                                     "netgen": bool(MP.MeshingPipeline.isNetgenAvailable()),
                                     "used": "netgen" if use_netgen else "tetgen"}
    if use_netgen:
        logic.requireNetgen()

    params = logic.getParameterNode()
    surf = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "in_surface")
    surf.SetAndObservePolyData(pd)
    outn = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "out_volume")
    remn = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "out_remeshed")
    params.inputSurface = surf
    params.outputMesh = outn
    params.outputRemeshedSurface = remn

    params.elementSizeMode = CMG.ElementSizeMode.EDGE_LENGTH
    params.targetEdgeLength = target_edge
    params.remeshSurface = bool(job.get("remesh_surface", True))
    params.remeshWall = True
    params.capSurface = False                    # closed surface: keep whatever ids it has
    params.mesher = CMG.Mesher.NETGEN if use_netgen else CMG.Mesher.TETGEN
    params.volumeElementScaleFactor = float(job.get("volume_scale", 0.8))
    params.boundaryLayer = bool(job.get("boundary_layer", True))
    params.boundaryLayerOnCaps = False
    params.numberOfSubLayers = int(job.get("sublayers", 2))
    params.subLayerRatio = 0.5
    params.boundaryLayerThicknessFactor = float(job.get("bl_factor", 0.25))
    params.numberOfSubsteps = 2000
    params.relaxation = 0.01
    params.localCorrectionFactor = 0.45

    report["parameters"] = {k: getattr(params, k) for k in
                            ("targetEdgeLength", "volumeElementScaleFactor", "boundaryLayer",
                             "boundaryLayerOnCaps", "numberOfSubLayers", "subLayerRatio",
                             "boundaryLayerThicknessFactor", "numberOfSubsteps")}
    report["parameters"]["mesher"] = str(params.mesher)
    report["parameters"]["capSurface"] = False

    def relay(text, level=None):
        say("  [pipeline] %s" % text)

    logic.logCallback = relay

    t0 = time.time()
    ok, err = True, None
    try:
        logic.processInThisProcess(params)
    except Exception as exc:
        ok, err = False, "%s: %s" % (type(exc).__name__, exc)
        say("MESHING FAILED: %s" % err)
        traceback.print_exc()
    report["meshing_ok"] = ok
    report["meshing_error"] = err
    report["meshing_seconds"] = round(time.time() - t0, 2)
    say("meshing ok=%s in %.1f s" % (ok, report["meshing_seconds"]))

    mesh = outn.GetMesh()
    if mesh is not None and mesh.GetNumberOfCells() > 0:
        w = vtk.vtkXMLUnstructuredGridWriter()
        w.SetFileName(str(outdir / "volume_mesh.vtu"))
        w.SetInputData(mesh)
        w.SetDataModeToAscii()
        w.Write()
        types = Counter(int(t) for t in
                        vtk.util.numpy_support.vtk_to_numpy(mesh.GetCellTypesArray()))
        ids_arr = mesh.GetCellData().GetArray("CellEntityIds")
        idhist = {}
        if ids_arr is not None:
            vals = vtk.util.numpy_support.vtk_to_numpy(ids_arr).astype(int).ravel()
            idhist = {str(k): int(v) for k, v in sorted(Counter(vals.tolist()).items())}
        report["volume_mesh"] = {
            "points": int(mesh.GetNumberOfPoints()),
            "cells": int(mesh.GetNumberOfCells()),
            "cell_types": {str(k): v for k, v in sorted(types.items())},
            "cell_entity_id_histogram": idhist,
            "bounds_mm": [round(v, 4) for v in mesh.GetBounds()],
        }
        say("volume mesh: %d points, %d cells, types %s, ids %s"
            % (mesh.GetNumberOfPoints(), mesh.GetNumberOfCells(),
               dict(sorted(types.items())), idhist))
    else:
        say("no volume mesh produced")

    rs = remn.GetMesh()
    if rs is not None and rs.GetNumberOfCells() > 0:
        w = vtk.vtkXMLPolyDataWriter()
        w.SetFileName(str(outdir / "remeshed_surface.vtp"))
        w.SetInputData(rs)
        w.SetDataModeToAscii()
        w.Write()
        report["remeshed_surface"] = {"points": int(rs.GetNumberOfPoints()),
                                      "cells": int(rs.GetNumberOfCells())}

    (outdir / "mesher_run.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    say("wrote %s" % (outdir / "mesher_run.json"))
    return 0


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    except Exception:
        traceback.print_exc()
    print("T039_RC=%d" % rc)
    sys.exit(rc)
