"""T-039 step 3: run SlicerVMTK's `CFD Mesh Generator` headless on the analytic tube.

Loads outputs/T-039/tube.stl (3 solids: inlet/outlet/wall, mm), builds a vtkPolyData
carrying VMTK's `CellEntityIds` cell array (wall=1, inlet=2, outlet=3 -- see
MeshingPipeline.wallCellEntityId), then runs the module's own pipeline
(CfdMeshGeneratorLogic, which inherits MeshingPipeline whole) with the Netgen engine
and a prismatic boundary layer, and writes:

    outputs/T-039/tube_mesh.vtu        volume mesh (unstructured grid)
    outputs/T-039/tube_remeshed.vtp    remeshed surface
    outputs/T-039/mesher_run.json      run report (paths, counts, cell type histogram)

Units: the STL is in mm; Slicer/VMTK work in mm, so no scaling is applied here.
Unit handling is dealt with at the OpenFOAM conversion step.
"""
import json
import os
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

import slicer
import vtk
from vtk.util import numpy_support  # noqa: F401  (kept for parity with the module)

OUT = Path(r"D:\项目\鼻腔建模\outputs\T-039")
TUBE = OUT / "tube.stl"
REPORT = OUT / "mesher_run.json"

LOG = []


def say(text):
    print(text, flush=True)
    LOG.append(str(text))


# ----------------------------------------------------------------------------
# 1. ASCII STL -> vtkPolyData with shared points + CellEntityIds cell array
# ----------------------------------------------------------------------------

def parse_stl_ascii(path):
    """{solid name: [ (v0, v1, v2), ... ]} preserving the solids the file declares."""
    solids = {}
    name = None
    tri = []
    for line in path.read_text(encoding="ascii", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("solid "):
            name = s[6:].strip()
            solids.setdefault(name, [])
        elif s.startswith("endsolid"):
            name = None
        elif s.startswith("vertex "):
            tri.append(tuple(float(v) for v in s.split()[1:4]))
            if len(tri) == 3:
                solids[name].append(tuple(tri))
                tri = []
    return solids


def build_polydata(solids, id_map):
    """Merge-by-coordinate polydata with an int `CellEntityIds` cell array."""
    point_ids = {}
    points = vtk.vtkPoints()

    def pid(p):
        i = point_ids.get(p)
        if i is None:
            i = points.InsertNextPoint(*p)
            point_ids[p] = i
        return i

    tris = vtk.vtkCellArray()
    ids = vtk.vtkIntArray()
    ids.SetName("CellEntityIds")
    counts = {}
    for name, idv in id_map.items():
        n = 0
        for triangle in solids[name]:
            a, b, c = (pid(p) for p in triangle)
            tris.InsertNextCell(3)
            tris.InsertCellPoint(a)
            tris.InsertCellPoint(b)
            tris.InsertCellPoint(c)
            ids.InsertNextValue(idv)
            n += 1
        counts[name] = n

    pd = vtk.vtkPolyData()
    pd.SetPoints(points)
    pd.SetPolys(tris)
    pd.GetCellData().AddArray(ids)
    return pd, counts


# ----------------------------------------------------------------------------

def main():
    report = {"schema": "t039_mesher_run/v1", "started": None, "steps": LOG}

    solids = parse_stl_ascii(TUBE)
    say("STL solids: %s" % {k: len(v) for k, v in solids.items()})

    # wall must be id 1 (MeshingPipeline.wallCellEntityId); caps are numbered above it.
    id_map = {"wall": 1, "inlet": 2, "outlet": 3}
    pd, tri_counts = build_polydata(solids, id_map)
    say("polydata: %d points, %d cells, per-solid %s"
        % (pd.GetNumberOfPoints(), pd.GetNumberOfCells(), tri_counts))
    report["surface"] = {"points": pd.GetNumberOfPoints(),
                         "cells": pd.GetNumberOfCells(),
                         "triangles_per_solid": tri_counts,
                         "cell_entity_ids": id_map}

    # --- module ---
    # The extension is installed on disk but not yet registered in Slicer-34645.ini
    # ("Skipping application restart"), so its lib paths are not on sys.path / the DLL
    # search path. Add them here rather than editing Slicer's settings.
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
    scripted = os.path.join(ext_root, "SlicerVMTK", "lib", "Slicer-5.12", "qt-scripted-modules")
    if scripted not in sys.path:
        sys.path.insert(0, scripted)
    import vtkvmtkMiscPython  # noqa: F401  (proves the VMTK bindings load)
    say("vtkvmtkMiscPython loaded from %s" % vtkvmtkMiscPython.__file__)
    import CfdMeshGenerator as CMG

    from CfdMeshGeneratorLib import MeshingPipeline as MP
    from CfdMeshGeneratorLib import Netgen as NetgenLib

    say("mesher availability: tetgen=%s netgen=%s"
        % (MP.MeshingPipeline.isTetGenAvailable(), MP.MeshingPipeline.isNetgenAvailable()))
    report["mesher_availability"] = {
        "tetgen": bool(MP.MeshingPipeline.isTetGenAvailable()),
        "netgen": bool(MP.MeshingPipeline.isNetgenAvailable()),
        "ftetwild": None,
    }

    logic = CMG.CfdMeshGeneratorLogic()
    if not logic.isNetgenAvailable():
        say("netgen not importable -> installing %s into Slicer's Python" % NetgenLib.REQUIREMENT)
        logic.installNetgen()
        say("netgen available now: %s" % logic.isNetgenAvailable())
    report["mesher_availability"]["netgen_after_install"] = bool(logic.isNetgenAvailable())
    logic.requireNetgen()

    params = logic.getParameterNode()
    surfaceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "tube_surface")
    surfaceNode.SetAndObservePolyData(pd)
    outNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "tube_volume_mesh")
    remNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "tube_remeshed_surface")

    params.inputSurface = surfaceNode
    params.outputMesh = outNode
    params.outputRemeshedSurface = remNode

    # --- meshing parameters (mm) ---
    params.elementSizeMode = CMG.ElementSizeMode.EDGE_LENGTH
    params.targetEdgeLength = 0.4            # mm, matches T-036 coarsest clean tube
    params.remeshSurface = True
    params.remeshWall = True
    params.capSurface = False                # surface arrives closed; keep its face ids
    params.mesher = CMG.Mesher.NETGEN
    params.volumeElementScaleFactor = 0.8
    params.netgenGrading = 0.3
    params.netgenOptimizationSteps = 3
    params.boundaryLayer = True
    params.boundaryLayerOnCaps = False       # layer on the wall only
    params.numberOfSubLayers = 2
    params.subLayerRatio = 0.5
    params.boundaryLayerThicknessFactor = 0.25
    params.numberOfSubsteps = 2000
    params.relaxation = 0.01
    params.localCorrectionFactor = 0.45
    params.cellEntityIdsArrayNames = "CellEntityIds, ModelFaceID"

    report["parameters"] = {
        "elementSizeMode": str(params.elementSizeMode),
        "targetEdgeLength_mm": params.targetEdgeLength,
        "remeshSurface": True,
        "capSurface": False,
        "mesher": str(params.mesher),
        "volumeElementScaleFactor": params.volumeElementScaleFactor,
        "netgenGrading": params.netgenGrading,
        "netgenOptimizationSteps": params.netgenOptimizationSteps,
        "boundaryLayer": True,
        "boundaryLayerOnCaps": False,
        "numberOfSubLayers": params.numberOfSubLayers,
        "subLayerRatio": params.subLayerRatio,
        "boundaryLayerThicknessFactor": params.boundaryLayerThicknessFactor,
        "numberOfSubsteps": params.numberOfSubsteps,
        "relaxation": params.relaxation,
        "localCorrectionFactor": params.localCorrectionFactor,
    }

    def relay(text, level=None):
        say("  [pipeline] %s" % text)

    logic.logCallback = relay

    t0 = time.time()
    ok = True
    err = None
    # processAndWait() would hand the surface to a MeshingWorker in a PythonSlicer of its
    # own; that worker would not carry the sys.path / DLL-directory fix made above (the
    # extension is not yet registered in Slicer-34645.ini), so the run is done in this
    # process - the same pipeline, same steps, same generateMesh() (module's own
    # processInThisProcess path, which it documents as the one for scripts and tests).
    try:
        logic.processInThisProcess(params)
    except Exception as exc:
        ok = False
        err = "%s: %s" % (type(exc).__name__, exc)
        say("MESHING FAILED: %s" % err)
        traceback.print_exc()
    elapsed = time.time() - t0
    report["meshing_ok"] = ok
    report["meshing_error"] = err
    report["meshing_seconds"] = round(elapsed, 2)
    report["meshing_path"] = "processInThisProcess"
    say("meshing finished ok=%s in %.1fs" % (ok, elapsed))

    # --- write outputs ---
    mesh = outNode.GetMesh()
    if mesh is not None and mesh.GetNumberOfCells() > 0:
        w = vtk.vtkXMLUnstructuredGridWriter()
        w.SetFileName(str(OUT / "tube_mesh.vtu"))
        w.SetInputData(mesh)
        w.SetDataModeToAscii()
        w.Write()
        w2 = vtk.vtkUnstructuredGridWriter()
        w2.SetFileName(str(OUT / "tube_mesh.vtk"))
        w2.SetInputData(mesh)
        w2.SetFileTypeToBinary()
        w2.Write()
        say("wrote tube_mesh.vtu / tube_mesh.vtk")

        types = Counter()
        arr = numpy_support.vtk_to_numpy(mesh.GetCellTypesArray())
        for t in arr:
            types[int(t)] += 1
        report["volume_mesh"] = {
            "points": mesh.GetNumberOfPoints(),
            "cells": mesh.GetNumberOfCells(),
            "cell_types": {str(k): v for k, v in sorted(types.items())},
            "cell_data_arrays": [mesh.GetCellData().GetArrayName(i)
                                 for i in range(mesh.GetCellData().GetNumberOfArrays())],
            "point_data_arrays": [mesh.GetPointData().GetArrayName(i)
                                  for i in range(mesh.GetPointData().GetNumberOfArrays())],
            "bounds_mm": [round(v, 4) for v in mesh.GetBounds()],
        }
        ids_arr = mesh.GetCellData().GetArray("CellEntityIds")
        if ids_arr is not None:
            idsv = numpy_support.vtk_to_numpy(ids_arr).astype(int).ravel()
            report["volume_mesh"]["cell_entity_id_histogram"] = {
                str(k): v for k, v in sorted(Counter(idsv.tolist()).items())}
        say("volume mesh: %d cells, types %s" % (mesh.GetNumberOfCells(),
                                                  dict(sorted(types.items()))))
    else:
        say("no volume mesh produced")

    surf = remNode.GetMesh()
    if surf is not None and surf.GetNumberOfCells() > 0:
        w = vtk.vtkXMLPolyDataWriter()
        w.SetFileName(str(OUT / "tube_remeshed.vtp"))
        w.SetInputData(surf)
        w.SetDataModeToAscii()
        w.Write()
        report["remeshed_surface"] = {"points": surf.GetNumberOfPoints(),
                                      "cells": surf.GetNumberOfCells()}
        say("wrote tube_remeshed.vtp (%d pts, %d cells)"
            % (surf.GetNumberOfPoints(), surf.GetNumberOfCells()))

    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    say("wrote %s" % REPORT)
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:
        traceback.print_exc()
        rc = 1
    print("T039_RC=%d" % rc)
    sys.exit(rc)
