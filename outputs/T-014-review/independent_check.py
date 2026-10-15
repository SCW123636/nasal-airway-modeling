"""T-014 fresh review: raw frozen evidence plus six-vertex production checks.

Never loads the full patient mesh, recrops CT, remeshes, or solves CFD.
"""
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(r"D:\项目\鼻腔建模")
OUT = ROOT / "outputs" / "T-014-review"
sys.path.insert(0, str(ROOT / "work" / "lib"))
from connectivity_opened_surface import flood_mask, signed_of
from auto_opening_pipeline import load_planes, build_placed, plane_basis, search_base


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def main():
    evidence_paths = [
        ROOT / "work/lib/partitioned_surface.py",
        ROOT / "work/lib/connectivity_opened_surface.py",
        ROOT / "work/lib/auto_opening_pipeline.py",
        ROOT / "work/lib/auto_anatomy_landmarks.py",
        ROOT / "work/lib/nasal_pipeline.py",
        ROOT / "work/06_auto_landmarks/p0/landmarks.json",
        Path(r"C:\ts_work\batch27_surfaces\p0\source_surface.vtp"),
        Path(r"C:\ts_work\batch27_opening\p0.json"),
        ROOT / "outputs/T-013/start_fingerprints.json",
        ROOT / "outputs/T-013/real_cases_results.json",
        ROOT / "outputs/T-013/mask_scope_results.json",
        ROOT / "outputs/T-013/synthetic_results.json",
        ROOT / "outputs/T-013/collision_nasopharynx_outlet.npz",
        Path(__file__),
    ]
    before = {str(p): sha(p) for p in evidence_paths}
    baseline = read(ROOT / "outputs/T-013/start_fingerprints.json")
    identity = []
    for item in baseline["dependencies"] + baseline["landmarks"]:
        if item["path"] in before:
            identity.append({"path": item["path"], "expected": item["sha256"].lower(),
                             "actual": before[item["path"]],
                             "matches_T013": item["sha256"].lower() == before[item["path"]]})
    assert all(item["matches_T013"] for item in identity)

    original = read(ROOT / "outputs/T-013/real_cases_results.json")["cases"]["p0"]
    report = read(Path(r"C:\ts_work\batch27_opening\p0.json"))
    lm = read(ROOT / "work/06_auto_landmarks/p0/landmarks.json")
    planes, provenance, source_sha, admitted = load_planes(
        ROOT / "work/06_auto_landmarks", None, "p0", allow_needs_review=False)
    admitted_planes, _, _, _ = load_planes(
        ROOT / "work/06_auto_landmarks", None, "p0", allow_needs_review=True)
    assert planes == admitted_planes == original["planes"]
    assert provenance == report["plane_source"] == "automatic_proposal"
    assert source_sha == report["plane_source_sha256"] == before[str(ROOT / "work/06_auto_landmarks/p0/landmarks.json")]
    assert report["source_sha256"] == before[str(Path(r"C:\ts_work\batch27_surfaces\p0\source_surface.vtp"))]
    assert report["search_origin"] == report["requested_search_origin"] == "reviewed"
    assert report["seed_mode"] == "roi" and report["decision"] == "escalated"
    assert all(value == 0.0 for value in report["offset_from_reviewed_mm"].values())
    assert not any(report["placement_evidence"]["entered_bisection"].values())
    assert all(value == 0.0 for row in report["descent_trace"] for value in row.values())
    bases = search_base(report["onset_offset_mm"], report["search_origin"])
    norms = {key: plane_basis(spec["normal_lps"])[0] for key, spec in planes.items()}
    placed = build_placed(planes, norms, bases, {key: 0.0 for key in planes})
    assert placed == planes
    parameter_chain = {
        "plane_source": provenance, "human_review_store_used": False,
        "clinical_status": report["clinical_status"], "source_sha256": source_sha,
        "search_origin": report["search_origin"], "base_offset_mm": bases,
        "offset_from_reviewed_mm": report["offset_from_reviewed_mm"],
        "entered_bisection": report["placement_evidence"]["entered_bisection"],
        "seed_mode": report["seed_mode"], "admitted_needs_review": admitted,
        "load_planes_with_or_without_allow_needs_review_identical": True,
        "placed_zero_equals_frozen_landmark_and_T013_planes": True,
        "outlet_passed_to_clip_and_flood": placed["nasopharynx_outlet"],
        "landmark_input_provenance": lm.get("input_provenance"),
        "scope": "calls load_planes/search_base/build_placed only; actual p0 process report reused",
    }

    # Independent literal known answer: negative edges {0,1} and {3,4}.
    # v2 is positive, v5 is on-plane. Small ROI contains v0 only.
    points = np.array([[-1, 0, 0], [-1, 3, 0], [1, 0, 1],
                       [-1, 20, 0], [-1, 23, 0], [0, 20, 1]], dtype=float)
    faces = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int64)
    spec = {"point_lps_mm": [0, 0, 0], "normal_lps": [1, 0, 0],
            "keep_positive": True,
            "roi_lps_mm": {"min": [-1.1, -.1, -.1], "max": [-.9, .1, .1]}}
    expected = np.array([True, True, False, False, False, False])
    actual, note = flood_mask(points, faces, spec, seed_mode="roi")
    assert np.array_equal(actual, expected)
    assert actual[1] and not ((points[1] >= spec["roi_lps_mm"]["min"]) &
                              (points[1] <= spec["roi_lps_mm"]["max"])).all()
    assert not actual[2] and not actual[5]
    broad_spec = dict(spec, roi_lps_mm={"min": [-1.1, -.1, -.1], "max": [-.9, 20.1, .1]})
    broad_expected = np.array([True, True, False, True, True, False])
    broad_actual, broad_note = flood_mask(points, faces, broad_spec, seed_mode="roi")
    assert np.array_equal(broad_expected, broad_actual)
    try:
        flood_mask(points, faces, dict(spec, keep_positive=False), seed_mode="roi")
    except ValueError as exc:
        reversed_error = str(exc)
        assert reversed_error == "no negative-side seed inside the reviewed ROI"
    else:
        raise AssertionError("reversed keep side unexpectedly has a seed")
    signed = signed_of(np.array([[-1, 0, 0], [1, 0, 0], [-.5e-7, 0, 0]]), spec)
    assert np.array_equal(signed, np.array([-1., 1., 0.]))
    known_answer = {"source": "independent_check.py literal points/faces and analytic negative-edge sets",
                    "points": points.tolist(), "faces": faces.tolist(), "spec": spec,
                    "expected": expected.tolist(), "actual": actual.tolist(), "production_note": note,
                    "broader_seed_roi_expected": broad_expected.tolist(),
                    "broader_seed_roi_actual": broad_actual.tolist(), "broader_seed_roi_note": broad_note,
                    "reverse_keep_side_error": reversed_error, "signed_tolerance_expected_and_actual": signed.tolist(),
                    "passed": True}

    # Recalculate from existing small collision artifact, not full patient geometry.
    collision = ROOT / "outputs/T-013/collision_nasopharynx_outlet.npz"
    with np.load(collision, allow_pickle=False) as data:
        triangles = data["triangles"]
        stored_signed = data["signed"]
        patch = data["patch"]
        saved_spec = json.loads(str(data["spec_json"]))
        assert saved_spec == placed["nasopharynx_outlet"]
        distances = signed_of(triangles.reshape(-1, 3), saved_spec).reshape(-1, 3)
        np.testing.assert_allclose(distances, stored_signed, rtol=0, atol=1e-12)
        lo, hi = np.array(saved_spec["roi_lps_mm"]["min"]), np.array(saved_spec["roi_lps_mm"]["max"])
        inside = ((triangles >= lo) & (triangles <= hi)).all(axis=(1, 2))
        values, counts = np.unique(patch, return_counts=True)
        subset = {"artifact_sha256": before[str(collision)], "triangles": len(triangles),
                  "patch_counts": {str(v): int(c) for v, c in zip(values, counts)},
                  "all_vertices_negative_triangles": int((distances < 0).all(axis=1).sum()),
                  "strict_straddling_triangles": int(((distances.min(1) < 0) & (distances.max(1) > 0)).sum()),
                  "all_vertices_inside_roi_triangles": int(inside.sum()),
                  "recalculated_min_mm": float(distances.min()), "recalculated_max_mm": float(distances.max()),
                  "stored_signed_matches_production_definition": True,
                  "saved_spec_matches_actual_zero_offset_plane": True}
    assert subset["triangles"] == subset["all_vertices_negative_triangles"] == 774
    assert subset["strict_straddling_triangles"] == subset["all_vertices_inside_roi_triangles"] == 0
    after = {str(p): sha(p) for p in evidence_paths}
    assert before == after
    result = {"recorded_at": datetime.now().astimezone().isoformat(),
              "identity": identity, "parameter_chain": parameter_chain,
              "independent_known_answer": known_answer, "existing_collision_artifact_recheck": subset,
              "fingerprints_before": before, "fingerprints_after": after, "all_read_inputs_unchanged": True,
              "full_patient_mesh_loaded": False, "patient_flood_or_clipper_rerun": False,
              "production_modified": False, "anatomy_approved": False,
              "task_status_assigned": False}
    path = OUT / "independent_results.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"result": str(path), "known_answer_passed": True,
                      "parameter_chain_passed": True, "collision_recheck": subset,
                      "inputs_unchanged": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
