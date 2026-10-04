"""Physical-coordinate preview tests use synthetic anisotropic, rotated images."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import SimpleITK as sitk

from boundary_preview import generate_preview


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def bounds(image):
    size = np.asarray(image.GetSize())
    corners = []
    for index in np.ndindex(*(2,) * 3):
        point = image.TransformIndexToPhysicalPoint(tuple(int(value) for value in (size - 1) * index))
        corners.append(point)
    values = np.asarray(corners)
    return values.min(axis=0).tolist(), values.max(axis=0).tolist()


class BoundaryPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="boundary_preview_")
        root = Path(self.temp.name)
        size = (32, 28, 24)
        self.ct = sitk.Image(size, sitk.sitkFloat32)
        self.ct.SetSpacing((1.2, 1.5, 2.0))
        self.ct.SetOrigin((-10.0, -20.0, 30.0))
        self.ct.SetDirection((0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0))
        values = np.full((size[2], size[1], size[0]), -950, dtype=np.float32)
        values[5:20, 7:23, 8:25] = 80
        self.ct = sitk.GetImageFromArray(values)
        self.ct.SetSpacing((1.2, 1.5, 2.0))
        self.ct.SetOrigin((-10.0, -20.0, 30.0))
        self.ct.SetDirection((0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0))
        self.airway = sitk.Image(size, sitk.sitkUInt8)
        airway = np.zeros((size[2], size[1], size[0]), dtype=np.uint8)
        airway[7:18, 9:21, 10:23] = 1
        self.airway = sitk.GetImageFromArray(airway)
        self.airway.CopyInformation(self.ct)
        sinus = np.zeros_like(airway)
        sinus[10:13, 12:17, 17:21] = 1
        self.sinus = sitk.GetImageFromArray(sinus)
        self.sinus.CopyInformation(self.ct)
        self.ct_path, self.airway_path, self.sinus_path = (root / name for name in ("ct.nii.gz", "airway.nii.gz", "sinus.nii.gz"))
        sitk.WriteImage(self.ct, str(self.ct_path))
        sitk.WriteImage(self.airway, str(self.airway_path))
        sitk.WriteImage(self.sinus, str(self.sinus_path))
        self.center = np.asarray(self.ct.TransformIndexToPhysicalPoint((16, 14, 12)))
        lo, hi = bounds(self.ct)
        self.roi = {"min": lo, "max": hi}

    def tearDown(self):
        self.temp.cleanup()

    def plane(self, normal, offset):
        normal = np.asarray(normal, dtype=float)
        point = self.center + normal * offset
        return {"status": "confirmed", "point_lps_mm": point.tolist(), "normal_lps": normal.tolist(),
                "roi_lps_mm": self.roi, "keep_positive": True}

    def controls(self):
        return {
            "openings": {"nostril_L": self.plane((1, 0, 0), -7),
                         "nostril_R": self.plane((-1, 0, 0), -7),
                         "nasopharynx_outlet": self.plane((0, 1, 0), -7)},
            "oral_exclusion": {"confirmed": True, "mode": "same_as_nasopharynx_outlet",
                               "boundary_ref": "nasopharynx_outlet"},
            "sinus_policy": {"confirmed": True, "policy": "exclude_sinuses",
                             "regions": ["maxillary", "frontal", "ethmoid", "sphenoid"]},
        }

    def test_rotated_physical_grid_generates_bound_manifest_and_real_images(self):
        controls = self.controls()
        binding = {"case": "u_0123456789abcdef", "patient_id": "patient_01", "revision": "original",
                   "ct_sha256": digest(self.ct_path), "label_sha256": {"airway": digest(self.airway_path)},
                   "candidate_sha256": "a" * 64, "landmark_review_sha256": "b" * 64}
        output = Path(self.temp.name) / "draft_previews" / "d_0123456789abcdef"
        manifest = generate_preview(self.ct_path, self.airway_path, controls, output,
                                    sinus_path=self.sinus_path, binding=binding, pixels=65, field_mm=45)
        self.assertEqual(manifest["status"], "generated")
        self.assertFalse(manifest["cfd_ready"])
        self.assertEqual(manifest["operations"]["mask_interpolation"], "nearest_neighbor")
        self.assertEqual(manifest["source_geometry"]["direction"], list(self.ct.GetDirection()))
        for name in ("axial.png", "coronal.png", "sagittal.png", "oral_overlay.png",
                     "sinus_overlay.png", "openings_overlay.png", "sinus_exclusion_mask.nii.gz",
                     "draft_airway.nii.gz", "manifest.json"):
            path = output / name
            self.assertTrue(path.is_file(), name)
            self.assertGreater(path.stat().st_size, 100, name)
        self.assertEqual(manifest["outputs"]["axial"]["sha256"], digest(output / "axial.png"))
        self.assertLess(manifest["voxel_counts"]["draft"], manifest["voxel_counts"]["source"])
        self.assertEqual(self.ct_path.read_bytes(), self.ct_path.read_bytes())

    def test_controls_are_scoped_and_a_new_directory_is_required(self):
        controls = self.controls()
        output = Path(self.temp.name) / "draft"
        manifest = generate_preview(self.ct_path, self.airway_path, controls, output,
                                    sinus_path=self.sinus_path, pixels=65, field_mm=45)
        self.assertEqual(manifest["status"], "exploratory")
        controls["openings"]["nostril_L"]["point_lps_mm"][0] += 1
        with self.assertRaises(FileExistsError):
            generate_preview(self.ct_path, self.airway_path, controls, output,
                             sinus_path=self.sinus_path, pixels=65, field_mm=45)
        second = Path(self.temp.name) / "draft_2"
        changed = generate_preview(self.ct_path, self.airway_path, controls, second,
                                   sinus_path=self.sinus_path, pixels=65, field_mm=45)
        self.assertNotEqual(manifest["parameters_sha256"], changed["parameters_sha256"])
        self.assertNotEqual(json.loads((output / "manifest.json").read_text())["parameters_sha256"],
                            changed["parameters_sha256"])

    def test_reviewable_draft_requires_sinus_mask_and_all_controls_stay_inside_ct(self):
        binding = {"case": "u_0123456789abcdef", "patient_id": "patient_01", "revision": "original",
                   "ct_sha256": digest(self.ct_path), "label_sha256": {"airway": digest(self.airway_path)},
                   "candidate_sha256": "a" * 64, "landmark_review_sha256": "b" * 64}
        with self.assertRaisesRegex(ValueError, "sinus exclusion"):
            generate_preview(self.ct_path, self.airway_path, self.controls(), Path(self.temp.name) / "bound",
                             binding=binding, pixels=65, field_mm=45)
        bad = self.controls()
        bad["openings"]["nostril_L"]["point_lps_mm"] = [1000, 1000, 1000]
        with self.assertRaisesRegex(ValueError, "outside CT"):
            generate_preview(self.ct_path, self.airway_path, bad, Path(self.temp.name) / "bad",
                             sinus_path=self.sinus_path, binding=binding, pixels=65, field_mm=45)


if __name__ == "__main__":
    unittest.main()
