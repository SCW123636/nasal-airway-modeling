# -*- coding: utf-8 -*-
"""Independent workspace/reference checks; generated fixtures stay in temp dirs."""

import contextlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np

import build_cfd_workspace as workspace
from cfd_contract import validate_result
import serve_cfd_workspace as server


class WorkspaceContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="nasal_workspace_test_")
        self.root = Path(self.tmp.name)
        self.base = self.root / "work" / "07_cfd_pipeline"
        self.patches = [mock.patch.object(workspace, "ROOT", self.root),
                        mock.patch.object(workspace, "BASE", self.base)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def analytic(self):
        item = workspace.analytic_pipe()
        result = json.loads((self.base / "reference" / "pipe_analytic" / "result.json").read_text(encoding="utf-8"))
        mesh = json.loads((self.base / "reference" / "pipe_analytic" / "viewer_mesh.json").read_text(encoding="utf-8"))
        return item, result, mesh

    def patient_fixture(self, **overrides):
        mesh = {"schema": "candidate_surface_preview/v1", "case": "p0",
                "status": "unreviewed_candidate_preview", "display_geometry_only": True,
                "review_required": True, "cfd_ready": False, "coordinate_system": "LPS", "unit": "mm",
                "affine_4x4_LPS": [[1, 0, 0, 10], [0, 1, 0, 20], [0, 0, 1, 30], [0, 0, 0, 1]],
                "geometry": {"vertices": [10, 20, 30, 11, 20, 30, 10, 21, 30], "indices": [0, 1, 2]},
                "source": {"mask_sha256": "a" * 64, "manifest_sha256": "b" * 64}, "qc": {}}
        mesh.update(overrides)
        path = self.base / "preview" / "p0" / "viewer_mesh.json"
        workspace.write_json(path, mesh)
        landmarks = {"case": "p0", "coordinate_system": "LPS", "unit": "mm", "landmarks": {
            "synthetic_point": {"label_zh": "测试候选", "label_en": "synthetic point",
                                "point_lps_mm": [10, 20, 30], "normal_lps": [0, 1, 0], "status": "proposed"}}}
        workspace.write_json(self.root / "work" / "06_auto_landmarks" / "p0" / "landmarks.json", landmarks)
        return path

    def feedback_audit_fixture(self, feedback):
        path = self.root / "work" / "06_auto_landmarks" / "feedback_review" / "audit.json"
        audit = {
            "schema": "landmark_feedback_audit/v1",
            "coordinate_system": "LPS",
            "unit": "mm",
            "feedback": feedback,
            "input_integrity_verified": True,
        }
        workspace.write_json(path, audit)
        return path

    def build(self):
        with contextlib.redirect_stdout(io.StringIO()):
            workspace.main()

    def test_analytic_radial_integral_recovers_volume_and_mass_flow(self):
        _, result, mesh = self.analytic()
        points = np.asarray(mesh["geometry"]["vertices"]).reshape(-1, 3)
        speed = np.asarray(result["fields"]["velocity"]["values"])[:, 2]
        section = np.isclose(points[:, 2], 0.0) & (points[:, 0] >= 0)
        r = points[section, 0] * 1e-3
        u = speed[section]
        order = np.argsort(r)
        r, u = r[order], u[order]
        self.assertEqual((len(r) - 1) % 2, 0)
        np.testing.assert_allclose(np.diff(r), r[1] - r[0], atol=1e-16)
        integrand = u * r
        integral = ((r[1] - r[0]) / 3.0) * (integrand[0] + integrand[-1]
                   + 4 * integrand[1:-1:2].sum() + 2 * integrand[2:-1:2].sum())
        q = 2 * math.pi * integral
        expected_q = 1e-3 / 60.0
        self.assertAlmostEqual(q / expected_q, 1.0, places=12)
        self.assertAlmostEqual(result["physics"]["rho_kg_m3"] * q, 2e-5, places=14)
        self.assertAlmostEqual(float(u.max()), 2 * expected_q / (math.pi * (2e-3) ** 2), places=12)

    def test_analytic_pressure_gradient_and_field_contract(self):
        item, result, mesh = self.analytic()
        points = np.asarray(mesh["geometry"]["vertices"]).reshape(-1, 3)
        pressure = np.asarray(result["fields"]["pressure"]["values"])
        q = 1e-3 / 60.0
        gradient = 8 * result["physics"]["mu_Pa_s"] * q / (math.pi * (2e-3) ** 4)
        np.testing.assert_allclose(pressure, gradient * (0.06 - points[:, 2] * 1e-3), atol=1e-12)
        self.assertTrue(validate_result(result)["valid"])
        self.assertEqual(item["type"], "analytic_reference")
        self.assertIsNone(result["geometry"]["case_id"])
        self.assertEqual(result["provenance"]["method"], "analytic_solution")
        self.assertIsNone(result["fields"]["turbulence_intensity"])
        self.assertEqual(result["turbulence_intensity_status"], "not_applicable")
        self.assertEqual(len(result["fields"]["velocity"]["values"]), len(points))
        self.assertEqual(len(pressure), len(points))
        self.assertLess(max(mesh["geometry"]["indices"]), len(points))
        self.assertFalse(mesh["cfd_ready"])

    def test_patient_workspace_keeps_all_flow_fields_null(self):
        self.patient_fixture()
        self.build()
        data = json.loads((self.base / "viewer" / "workspace_data.json").read_text(encoding="utf-8"))
        self.assertEqual(data["patient_scan_count"], 1)
        self.assertEqual(data["patient_cfd_results"], 0)
        patient = next(case for case in data["cases"] if case["type"] == "patient_preview")
        result = patient["result"]
        self.assertTrue(validate_result(result)["valid"])
        self.assertEqual(result["geometry"]["review_status"], "pending")
        self.assertEqual(result["fields"], {"velocity": None, "pressure": None, "turbulence_intensity": None})
        self.assertEqual(patient["landmarks"][0]["point_lps_mm"], [10, 20, 30])
        self.assertEqual(sum(c["type"] == "analytic_reference" for c in data["cases"]), 1)
        self.assertEqual(data["feedback_audit"]["status"], "not_generated")

    def test_patient_workspace_exposes_feedback_audit_without_unlocking_cfd(self):
        self.patient_fixture()
        self.feedback_audit_fixture([
            {"bound_to_current_proposal": True},
            {"bound_to_current_proposal": False},
            {"bound_to_current_proposal": False},
        ])
        self.build()
        data = json.loads((self.base / "viewer" / "workspace_data.json").read_text(encoding="utf-8"))
        audit = data["feedback_audit"]
        self.assertEqual(audit["status"], "diagnostic_review_complete")
        self.assertEqual(audit["observations"], 3)
        self.assertEqual(audit["matched_current_proposals"], 1)
        self.assertEqual(audit["unresolved_or_mismatched"], 2)
        self.assertTrue(audit["original_proposals_unchanged"])
        self.assertFalse(audit["clinical_acceptance"])
        self.assertEqual(data["patient_cfd_results"], 0)
        patient = next(case for case in data["cases"] if case["type"] == "patient_preview")
        self.assertEqual(patient["result"]["fields"], {"velocity": None, "pressure": None, "turbulence_intensity": None})

    def test_patient_mesh_cannot_carry_an_analytic_reference_result(self):
        _, analytic, _ = self.analytic()
        self.patient_fixture(result=analytic)
        with self.assertRaises(ValueError):
            self.build()

    def test_patient_mesh_identity_and_units_must_match(self):
        for override in ({"case": "p1"}, {"coordinate_system": "RAS"}, {"unit": "m"}):
            with self.subTest(override=override):
                self.patient_fixture(**override)
                with self.assertRaises(ValueError):
                    self.build()

    def test_patient_result_contract_rejects_reference_fields(self):
        _, analytic, _ = self.analytic()
        result = {"schema": "nasal_cfd_result/v1", "type": "patient_preview",
                  "geometry": {"kind": "patient", "case_id": "p0", "review_status": "pending"},
                  "clinical_validation": "not_validated", "provenance": {"method": "segmentation_surface_preview"},
                  "fields": analytic["fields"]}
        self.assertFalse(validate_result(result)["valid"])

    def test_landmark_identity_units_and_numbers_must_match_patient(self):
        for change in ({"case": "p1"}, {"coordinate_system": "RAS"}, {"unit": "m"},
                       {"bad_point": [1, 2]}, {"bad_point": [True, 2, 3]}):
            with self.subTest(change=change):
                self.patient_fixture()
                path = self.root / "work" / "06_auto_landmarks" / "p0" / "landmarks.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                if "bad_point" in change:
                    data["landmarks"]["synthetic_point"]["point_lps_mm"] = change["bad_point"]
                else:
                    data.update(change)
                workspace.write_json(path, data)
                with self.assertRaises(ValueError):
                    self.build()


class LocalServerScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="nasal_server_scope_test_")
        root = Path(self.tmp.name)
        self.base = root / "07"
        self.review = root / "06"
        self.base.mkdir()
        self.review.mkdir()
        self.handler = object.__new__(server.Handler)
        self.progress = root / "progress.html"
        self.method = root / "08"
        self.method.mkdir()
        self.patches = [mock.patch.object(server, "BASE", self.base), mock.patch.object(server, "REVIEW", self.review), mock.patch.object(server, "PROGRESS", self.progress), mock.patch.object(server, "METHOD", self.method)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def test_normal_and_review_routes_stay_in_their_roots(self):
        self.assertEqual(Path(self.handler.translate_path("/viewer/index.html?x=../secret")), self.base / "viewer" / "index.html")
        self.assertEqual(Path(self.handler.translate_path("/landmark-review/p0/review.png")), self.review / "p0" / "review.png")
        self.assertEqual(Path(self.handler.translate_path("/progress/index.html")), self.progress)
        self.assertEqual(Path(self.handler.translate_path("/")), self.base / "workspace" / "index.html")
        self.assertEqual(Path(self.handler.translate_path("/index.html")), self.base / "workspace" / "index.html")
        self.assertEqual(Path(self.handler.translate_path("/method/plane-preview.html?embedded=1")), self.method / "plane-preview.html")

    def test_traversal_and_windows_paths_do_not_escape(self):
        for path in ("/../../secrets.txt", "/%2e%2e/%2e%2e/secrets.txt", "/..%5c..%5csecrets.txt",
                     "/C:/Windows/win.ini", "/landmark-review/../../secrets.txt",
                     "/landmark-review/..%2f..%2fsecrets.txt", "/method/../../secrets.txt",
                     "/method/..%5c..%5csecrets.txt"):
            with self.subTest(path=path):
                resolved = Path(self.handler.translate_path(path)).resolve()
                allowed = (self.review if path.startswith("/landmark-review/") else self.method if path.startswith("/method/") else self.base).resolve()
                self.assertTrue(resolved.is_relative_to(allowed), str(resolved))
                self.assertEqual(resolved.name, "__not_found__")

    def test_server_binds_only_loopback(self):
        fake = mock.Mock()
        with mock.patch.object(server, "ThreadingHTTPServer", return_value=fake) as factory, \
             mock.patch("sys.argv", ["serve_cfd_workspace.py", "--port", "12345"]), \
             contextlib.redirect_stdout(io.StringIO()):
            server.main()
        self.assertEqual(factory.call_args.args[0], ("127.0.0.1", 12345))
        fake.serve_forever.assert_called_once()


class DisplayCoordinateTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the viewer coordinate function check")
    def test_lps_to_display_is_single_centered_rigid_rotation(self):
        path = Path(__file__).resolve().parents[1] / "07_cfd_pipeline" / "viewer" / "viewer.js"
        js = path.read_text(encoding="utf-8")
        match = re.search(r"^function lpsToView\(.*$", js, re.MULTILINE)
        self.assertIsNotNone(match)
        code = 'const assert=require("node:assert/strict");const THREE={Vector3:class{constructor(x,y,z){this.v=[x,y,z];}}};\n'
        code += match.group(0) + '\n'
        code += 'assert.deepEqual(lpsToView([12,23,34],[10,20,30]).v,[2,4,-3]);\n'
        code += 'const p=lpsToView([12,23,34],[10,20,30]).v;assert.equal(p.reduce((s,v)=>s+v*v,0),29);\n'
        completed = subprocess.run([shutil.which("node")], input=code, text=True, capture_output=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the viewer field display check")
    def test_ti_fraction_is_displayed_as_percent_without_unmasking_null(self):
        path = Path(__file__).resolve().parents[1] / "07_cfd_pipeline" / "viewer" / "viewer.js"
        js = path.read_text(encoding="utf-8")
        match = re.search(r"^function fieldValues\(.*$", js, re.MULTILINE)
        self.assertIsNotNone(match)
        code = 'const assert=require("node:assert/strict");\n'
        code += 'let meshData={result:{fields:{turbulence_intensity:{unit:"1",display_unit:"%",association:"point",values:[0.05,null,0.2]},velocity:{unit:"m/s",association:"point",values:[[3,4,0],[0,0,2]]}}}};\n'
        code += match.group(0) + '\n'
        code += 'const before=JSON.stringify(meshData);assert.deepEqual(fieldValues("turbulence_intensity"),[5,null,20]);\n'
        code += 'assert.deepEqual(fieldValues("velocity"),[5,2]);assert.equal(JSON.stringify(meshData),before);\n'
        code += 'meshData.result.fields.turbulence_intensity=null;assert.equal(fieldValues("turbulence_intensity"),null);\n'
        completed = subprocess.run([shutil.which("node")], input=code, text=True, capture_output=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
