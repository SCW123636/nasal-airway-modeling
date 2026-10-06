"""Build and reload a local Slicer review bundle; never confirm patient boundaries.

Run with Slicer --no-main-window --testing --python-script <this file>.
NASAL_REVIEW_VERIFY=1 reloads the generated MRB in a fresh Slicer process.
Large artifacts remain in C:/ts_work/patient_surface_audit_20261005.
"""

import hashlib
import json
import os
from pathlib import Path
import traceback

import numpy as np
import slicer
import vtk


WORK = Path(__file__).resolve().parents[1]
OUT = Path(r"C:\ts_work\patient_surface_audit_20261005")
CT = Path(r"C:\ts_work\p0\ct.nii.gz")
MASK = WORK / "05_ts_seg/p0/anatomy/main_nasal_airway_T300_provisional.nii.gz"
PLANES = WORK / "06_auto_landmarks/p0/review_config_proposed.json"
SCENE = OUT / "p0_boundary_review_proposed.mrb"
REFERENCES = ("nasal_cavity_left", "nasal_cavity_right", "nasopharynx",
              "oropharynx", "hard_palate", "soft_palate")
COLORS = {"nostril_L": (0.2, 0.8, 0.45), "nostril_R": (0.2, 0.6, 1.0),
          "nasopharynx_outlet": (1.0, 0.75, 0.15)}
LPS_TO_RAS = np.array([-1.0, -1.0, 1.0])


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_label(path, name):
    node = slicer.util.loadLabelVolume(str(path))
    if node is None:
        raise RuntimeError("Cannot load " + str(path))
    node.SetName(name)
    return node


def verify_scene(proposals):
    volume = slicer.util.getNode("p0_CT")
    candidate = slicer.util.getNode("p0_T300_candidate_PROPOSED")
    segmentation = slicer.util.getNode("p0_airway_PROPOSED")
    source = load_label(MASK, "verification_source")
    source_array = slicer.util.arrayFromVolume(source)
    matrix = vtk.vtkMatrix4x4()
    volume.GetIJKToRASMatrix(matrix)
    ct_affine = np.array([[matrix.GetElement(i, j) for j in range(4)] for i in range(4)])
    source.GetIJKToRASMatrix(matrix)
    mask_affine = np.array([[matrix.GetElement(i, j) for j in range(4)] for i in range(4)])
    candidate.GetIJKToRASMatrix(matrix)
    stored_affine = np.array([[matrix.GetElement(i, j) for j in range(4)] for i in range(4)])
    if not np.allclose(ct_affine, mask_affine, atol=1e-5, rtol=0):
        raise RuntimeError("CT and mask geometry mismatch")
    if not np.allclose(mask_affine, stored_affine, atol=1e-8, rtol=0):
        raise RuntimeError("Bundle mask affine changed")
    if not np.array_equal(slicer.util.arrayFromVolume(candidate), source_array):
        raise RuntimeError("Bundle mask array changed")
    segment_id = segmentation.GetSegmentation().GetSegmentIdBySegmentName("T300_candidate")
    imported_array = slicer.util.arrayFromSegmentBinaryLabelmap(segmentation, segment_id, candidate)
    if not np.array_equal(imported_array > 0, source_array > 0):
        raise RuntimeError("Segmentation import changed voxels")
    slicer.mrmlScene.RemoveNode(source)
    checked_planes = {}
    for name, spec in proposals["planes_lps"].items():
        if name not in COLORS:
            continue
        node = slicer.util.getNode(name + "_PROPOSED")
        actual_origin, actual_normal = [0.0] * 3, [0.0] * 3
        node.GetOriginWorld(actual_origin)
        node.GetNormalWorld(actual_normal)
        if not np.allclose(actual_origin, LPS_TO_RAS * spec["point_lps_mm"], atol=1e-7, rtol=0):
            raise RuntimeError("Plane position mismatch: " + name)
        normal = np.asarray(spec["normal_lps"], dtype=float)
        normal /= np.linalg.norm(normal)
        if not np.allclose(actual_normal, LPS_TO_RAS * normal, atol=1e-7, rtol=0):
            raise RuntimeError("Plane normal mismatch: " + name)
        if node.GetAttribute("review_status") != "proposed":
            raise RuntimeError("Plane status changed")
        roi = slicer.util.getNode(name + "_ROI")
        center = list(roi.GetCenter())
        size = list(roi.GetSize())
        low, high = np.array(spec["roi_lps_mm"]["min"]), np.array(spec["roi_lps_mm"]["max"])
        expected_center = LPS_TO_RAS * (low + high) / 2
        expected_size = high - low
        # In Slicer 5.12.4, SetSize rounds the center at float32 resolution.
        # Bound that measured API effect separately from plane coordinates.
        center_tolerance = float(np.max(np.abs(expected_center.astype(np.float32).astype(float)
                                               - expected_center))) + 1e-7
        center_error = float(np.max(np.abs(np.asarray(center) - expected_center)))
        size_error = float(np.max(np.abs(np.asarray(size) - expected_size)))
        if center_error > center_tolerance:
            raise RuntimeError(f"ROI center changed: {name}, actual={center}, expected={expected_center.tolist()}, error={center_error}")
        if size_error > 1e-7:
            raise RuntimeError(f"ROI size changed: {name}, actual={size}, expected={expected_size.tolist()}, error={size_error}")
        checked_planes[name] = {"origin_ras_mm": actual_origin, "normal_ras": actual_normal,
                                "status": "proposed", "roi_verified": True,
                                "roi_center_max_abs_error_mm": center_error,
                                "roi_center_rounding_bound_mm": center_tolerance,
                                "roi_size_max_abs_error_mm": size_error}
    reference_counts = {}
    refs = slicer.util.getNode("p0_anatomy_REFERENCES")
    for name in REFERENCES:
        reference = slicer.util.getNode(name + "_REFERENCE")
        current = load_label(Path(r"C:\ts_work\p0\masks") / (name + ".nii.gz"), "reference_verification")
        if not np.array_equal(slicer.util.arrayFromVolume(reference), slicer.util.arrayFromVolume(current)):
            raise RuntimeError("Reference array changed: " + name)
        reference.GetIJKToRASMatrix(matrix)
        reference_affine = np.array([[matrix.GetElement(i, j) for j in range(4)] for i in range(4)])
        current.GetIJKToRASMatrix(matrix)
        current_affine = np.array([[matrix.GetElement(i, j) for j in range(4)] for i in range(4)])
        if not np.allclose(reference_affine, current_affine, atol=1e-8, rtol=0):
            raise RuntimeError("Reference affine changed: " + name)
        reference_id = refs.GetSegmentation().GetSegmentIdBySegmentName(name)
        reference_array = slicer.util.arrayFromSegmentBinaryLabelmap(refs, reference_id, reference)
        if not np.array_equal(reference_array > 0, slicer.util.arrayFromVolume(current) > 0):
            raise RuntimeError("Reference segmentation changed: " + name)
        reference_counts[name] = int(np.count_nonzero(slicer.util.arrayFromVolume(reference)))
        slicer.mrmlScene.RemoveNode(current)
    return {"ct_size_xyz": list(volume.GetImageData().GetDimensions()),
            "mask_size_xyz": list(candidate.GetImageData().GetDimensions()),
            "mask_voxels": int(np.count_nonzero(source_array)),
            "ct_mask_affine_matches": True, "mask_array_unchanged": True,
            "segmentation_array_matches_mask": True, "planes": checked_planes,
            "reference_arrays_unchanged": True, "reference_affines_unchanged": True,
            "reference_segmentations_match": True, "reference_voxel_counts": reference_counts}


def build(proposals):
    volume = slicer.util.loadVolume(str(CT))
    if volume is None:
        raise RuntimeError("CT load failed")
    volume.SetName("p0_CT")
    volume.GetDisplayNode().AutoWindowLevelOff()
    volume.GetDisplayNode().SetWindowLevel(1600, -200)
    candidate = load_label(MASK, "p0_T300_candidate_PROPOSED")
    segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "p0_airway_PROPOSED")
    segmentation.CreateDefaultDisplayNodes()
    segmentation.SetReferenceImageGeometryParameterFromVolumeNode(volume)
    if not slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(candidate, segmentation):
        raise RuntimeError("Mask import failed")
    segment = segmentation.GetSegmentation().GetNthSegment(0)
    segment.SetName("T300_candidate")
    segment.SetColor(0.2, 0.8, 0.8)
    segmentation.GetSegmentation().SetConversionParameter("Smoothing factor", "0.0")
    segmentation.CreateClosedSurfaceRepresentation()
    segmentation.GetDisplayNode().SetOpacity3D(0.35)
    segmentation.GetDisplayNode().SetOpacity2DFill(0.18)
    segmentation.SetAttribute("review_status", "proposed")
    segmentation.SetAttribute("patient_cfd_allowed", "false")
    segmentation.SetAttribute("mask_sha256", digest(MASK))
    refs = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "p0_anatomy_REFERENCES")
    refs.CreateDefaultDisplayNodes()
    refs.SetReferenceImageGeometryParameterFromVolumeNode(volume)
    for name in REFERENCES:
        reference = load_label(Path(r"C:\ts_work\p0\masks") / (name + ".nii.gz"), name + "_REFERENCE")
        if not slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(reference, refs):
            raise RuntimeError("Reference import failed: " + name)
        refs.GetSegmentation().GetNthSegment(refs.GetSegmentation().GetNumberOfSegments() - 1).SetName(name)
    refs.GetDisplayNode().SetVisibility(False)
    for name, color in COLORS.items():
        spec = proposals["planes_lps"][name]
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", name + "_PROPOSED")
        node.SetPlaneType(node.PlaneTypePointNormal)
        node.AddControlPoint(vtk.vtkVector3d(*(LPS_TO_RAS * spec["point_lps_mm"])))
        node.SetOriginWorld((LPS_TO_RAS * spec["point_lps_mm"]).tolist())
        node.SetNormalWorld((LPS_TO_RAS * spec["normal_lps"]).tolist())
        node.SetSizeMode(node.SizeModeAbsolute)
        node.SetSize(20.0, 20.0)
        node.SetAttribute("review_status", "proposed")
        node.SetAttribute("source_proposal_sha256", digest(PLANES))
        node.SetAttribute("roi_lps_mm", json.dumps(spec["roi_lps_mm"]))
        node.CreateDefaultDisplayNodes()
        node.GetDisplayNode().SetSelectedColor(*color)
        node.GetDisplayNode().SetOpacity(0.25)
        low, high = np.array(spec["roi_lps_mm"]["min"]), np.array(spec["roi_lps_mm"]["max"])
        roi = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsROINode", name + "_ROI")
        roi.SetCenter((LPS_TO_RAS * (low + high) / 2).tolist())
        roi.SetSize((high - low).tolist())
        roi.SetLocked(True)
        roi.CreateDefaultDisplayNodes()
        roi.GetDisplayNode().SetSelectedColor(*color)
        roi.GetDisplayNode().SetFillVisibility(False)
        roi.GetDisplayNode().SetOpacity(0.3)
    text = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTextNode", "Review_scope")
    text.SetText("p0 provisional candidate. Three proposed planes and ROI boxes only. "
                 "No crop, boundary confirmation, sinus/oral approval, mesh or CFD result. "
                 "LPS to Slicer RAS: negate x and y; keep z. Plane display rectangle is 20 mm; "
                 "actual crop domain is the ROI box. References are hidden by default.")
    slicer.util.setSliceViewerLayers(background=volume)
    if slicer.app.layoutManager() is not None:
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
        slicer.util.resetThreeDViews()
        slicer.util.resetSliceViews()
        focus = LPS_TO_RAS * proposals["planes_lps"]["nostril_L"]["point_lps_mm"]
        slicer.modules.markups.logic().JumpSlicesToLocation(*focus, True)


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    sources = {"ct": CT, "mask": MASK, "planes": PLANES}
    sources.update({name: Path(r"C:\ts_work\p0\masks") / (name + ".nii.gz") for name in REFERENCES})
    before = {name: digest(path) for name, path in sources.items()}
    proposals = json.loads(PLANES.read_text(encoding="utf-8"))
    reloading = os.environ.get("NASAL_REVIEW_VERIFY") == "1"
    if reloading:
        if not slicer.util.loadScene(str(SCENE)):
            raise RuntimeError("MRB reload failed")
    else:
        build(proposals)
    checks = verify_scene(proposals)
    if not reloading:
        if SCENE.exists():
            raise FileExistsError("Preserve existing bundle; use a new output directory")
        if not slicer.util.saveScene(str(SCENE)):
            raise RuntimeError("MRB save failed")
    if {name: digest(path) for name, path in sources.items()} != before:
        raise RuntimeError("Source changed during scene preparation")
    report = {"status": "reload_verified" if reloading else "saved_pending_reload",
              "verification_script_sha256": digest(Path(__file__)),
              "slicer_version": slicer.app.applicationVersion, "scene": str(SCENE),
              "scene_sha256": digest(SCENE), "source_sha256": before, "checks": checks,
              "patient_cfd_results": 0, "medical_review_status": "pending",
              "operations": {"source_modified": False, "cropping": False, "smoothing": False}}
    name = "slicer_reload.json" if reloading else "slicer_build.json"
    (OUT / name).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


try:
    run()
except Exception:
    OUT.mkdir(parents=True, exist_ok=True)
    import time
    (OUT / ("slicer_failure_" + str(time.time_ns()) + ".log")).write_text(
        traceback.format_exc(), encoding="utf-8")
    slicer.util.exit(1)
else:
    slicer.util.exit(0)
