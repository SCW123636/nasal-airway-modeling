"""Synthetic safety regressions for the QC gate; no patient data required."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import SimpleITK as sitk

import ts_quality_gate as gate


class LabelIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.ct = np.full((5, 5, 5), -900, dtype=np.int16)
        self.reference = sitk.GetImageFromArray(self.ct)
        self.failures, self.warnings = [], []

    def audit(self, array, name="nasal_cavity_left", origin=None):
        image = sitk.GetImageFromArray(array.astype(np.uint8))
        if origin is not None:
            image.SetOrigin(origin)
        return gate.audit_label(name, image, self.reference, self.ct,
                                self.failures, self.warnings)

    def test_shape_mismatch_fails_before_hu_indexing(self):
        result, usable = self.audit(np.ones((4, 5, 5), dtype=bool))
        self.assertIsNone(usable)
        self.assertIsNone(result["raw_semantic_HU"])
        self.assertIsNone(result["air_voxels_HU_lt_minus300"])
        self.assertIn("array shape mismatch: nasal_cavity_left", self.failures)

    def test_same_shape_different_origin_is_not_usable(self):
        result, usable = self.audit(np.ones_like(self.ct), origin=(2, 0, 0))
        self.assertTrue(result["array_shape_matches_ct"])
        self.assertIsNone(usable)
        self.assertIn("geometry mismatch: nasal_cavity_left", self.failures)

    def test_empty_required_label_is_a_hard_failure(self):
        result, _ = self.audit(np.zeros_like(self.ct))
        self.assertEqual(result["voxels"], 0)
        self.assertIn("required label empty: nasal_cavity_left", self.failures)

    def test_empty_reference_label_is_a_warning(self):
        self.audit(np.zeros_like(self.ct), name="hard_palate")
        self.assertFalse(self.failures)
        self.assertIn("reference label empty: hard_palate", self.warnings)

    def test_required_label_without_air_is_a_hard_failure(self):
        self.ct[:] = 120
        result, _ = self.audit(np.ones_like(self.ct))
        self.assertEqual(result["raw_semantic_HU"]["HU_gt0_voxels"], self.ct.size)
        self.assertIn("required label has no air below -300 HU: nasal_cavity_left", self.failures)

    def test_raw_hu_is_measured_before_threshold_intersection(self):
        mask = np.zeros_like(self.ct, dtype=bool)
        mask[1, 1, 1:3] = True
        self.ct[1, 1, 2] = 120
        result, _ = self.audit(mask)
        self.assertEqual(result["raw_semantic_HU"]["max"], 120)
        self.assertEqual(result["raw_semantic_HU"]["HU_gt0_voxels"], 1)
        self.assertEqual(result["air_fraction_HU_lt_minus300"], 0.5)
        self.assertFalse(self.failures)


class ConnectivityTests(unittest.TestCase):
    def setUp(self):
        self.source = np.zeros((7, 7, 7), dtype=bool)
        self.target = np.zeros_like(self.source)
        self.source[1, 1, 1] = True

    def test_corner_contact_is_not_a_face_connected_path(self):
        self.target[2, 2, 2] = True
        self.assertFalse(gate.pathway_evidence(self.source, self.target, 6)["shared_path_exists"])
        evidence = gate.pathway_evidence(self.source, self.target, 26)
        self.assertTrue(evidence["direct_contact"])
        self.assertTrue(evidence["shared_path_exists"])
        union = self.source | self.target
        self.assertEqual(gate.component_summary(union, 0.001, 6)["count"], 2)
        self.assertEqual(gate.component_summary(union, 0.001, 26)["count"], 1)

    def test_edge_contact_is_not_a_face_connected_path(self):
        self.target[1, 2, 2] = True
        self.assertFalse(gate.pathway_evidence(self.source, self.target, 6)["direct_contact"])
        self.assertTrue(gate.pathway_evidence(self.source, self.target, 26)["direct_contact"])

    def test_face_contact_provides_discrete_path_evidence(self):
        self.target[1, 1, 2] = True
        evidence = gate.pathway_evidence(self.source, self.target, 6)
        self.assertTrue(evidence["largest_source_component_reaches_target"])
        self.assertEqual(evidence["source_fraction_reaching_target"], 1.0)

    def test_tiny_connected_fragment_does_not_validate_dominant_source(self):
        self.source[5, 5, 3:6] = True
        self.target[1, 1, 2] = True
        evidence = gate.pathway_evidence(self.source, self.target, 6)
        self.assertTrue(evidence["shared_path_exists"])
        self.assertFalse(evidence["largest_source_component_reaches_target"])
        self.assertEqual(evidence["source_fraction_reaching_target"], 0.25)
        self.assertEqual(evidence["largest_source_component_voxels"], 3)

    def test_empty_target_is_explicitly_unavailable(self):
        evidence = gate.pathway_evidence(self.source, self.target, 6)
        self.assertEqual(evidence["status"], "unavailable_empty_source_or_target")
        self.assertFalse(evidence["shared_path_exists"])


class FilePipelineTests(unittest.TestCase):
    def run_case(self, left_override=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "masks").mkdir()
            ct = np.full((7, 7, 7), -900, dtype=np.int16)
            ct[3, 3, 1] = 120
            sitk.WriteImage(sitk.GetImageFromArray(ct), str(root / "ct.nii.gz"))
            masks = {name: np.zeros_like(ct, dtype=np.uint8) for name in gate.CLASSES}
            masks["nasal_cavity_left"][3, 3, 1:3] = 1
            masks["nasal_cavity_right"][3, 3, 4:6] = 1
            masks["nasopharynx"][3, 3, 3] = 1
            if left_override is not None:
                masks["nasal_cavity_left"] = left_override
            for name, mask in masks.items():
                sitk.WriteImage(sitk.GetImageFromArray(mask), str(root / "masks" / (name + ".nii.gz")))
            with mock.patch.object(gate, "save_overlay"), contextlib.redirect_stdout(io.StringIO()):
                code = gate.main(["synthetic", "--data-dir", str(root)])
            return code, json.loads((root / "gate_synthetic.json").read_text(encoding="utf-8"))

    def test_full_pipeline_retains_old_fields_without_claiming_medical_pass(self):
        code, report = self.run_case()
        self.assertEqual(code, 0)
        self.assertEqual(report["data_integrity_status"], "pass")
        self.assertEqual(report["overall_status"], "provisional")
        self.assertFalse(report["medical_or_cfd_validation_pass"])
        candidate = report["semantic_air_candidate"]
        self.assertTrue(candidate["HU_purity_pass"])
        self.assertEqual(candidate["HU_gt0_voxels"], 0)
        self.assertEqual(candidate["raw_semantic_HU_before_threshold"]["HU_gt0_voxels"], 1)
        self.assertIn("construction invariant", candidate["HU_purity_interpretation"])
        self.assertTrue(report["nasal_to_nasopharynx_contact"]["left_touches_nasopharynx_26_neighborhood"])
        self.assertEqual(report["nasal_to_nasopharynx_paths"]["left"]["inlet_to_outlet_patency"], "not_assessed")

    def test_full_pipeline_shape_mismatch_writes_failure_report(self):
        code, report = self.run_case(np.ones((6, 7, 7), dtype=np.uint8))
        self.assertEqual(code, 1)
        self.assertEqual(report["overall_status"], "fail")
        self.assertIn("array shape mismatch: nasal_cavity_left", report["hard_failures"])

    def test_full_pipeline_empty_required_label_writes_failure_report(self):
        code, report = self.run_case(np.zeros((7, 7, 7), dtype=np.uint8))
        self.assertEqual(code, 1)
        self.assertIn("required label empty: nasal_cavity_left", report["hard_failures"])


if __name__ == "__main__":
    unittest.main()
