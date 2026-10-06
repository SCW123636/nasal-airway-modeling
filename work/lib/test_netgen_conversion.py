"""Synthetic format and topology checks, never patient acceptance evidence."""

from pathlib import Path
import tempfile
import unittest

import meshio
import numpy as np

from netgen_vol_to_msh import convert_arrays
from repair_boundary_tetrahedra import repair


POINTS = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]])
FACES = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]])
TETS = np.array([[0, 1, 2, 3]])
DESCRIPTORS = [7, 11, 19, 23]
NASAL = {7: "nostril_L", 11: "nostril_R", 19: "nasopharynx_outlet", 23: "wall"}
TUBE = {7: "inlet", 11: "outlet", 19: "wall", 23: "wall"}


class ConversionTests(unittest.TestCase):
    def convert(self, **overrides):
        values = dict(points=POINTS, triangles=FACES, descriptors=DESCRIPTORS,
                      tetrahedra=TETS, mapping=NASAL, profile="nasal", unit="mm")
        values.update(overrides)
        return convert_arrays(**values)

    def test_mm_and_m_produce_same_si_mesh(self):
        mm, report = self.convert()
        meters, _ = self.convert(points=POINTS / 1000, unit="m")
        np.testing.assert_array_equal(mm.points, meters.points)
        self.assertAlmostEqual(report["volume_m3"], 1e-9 / 6, places=20)
        self.assertFalse(report["patient_solver_allowed"])

    def test_scrambled_descriptors_preserve_four_independent_patches(self):
        mesh, report = self.convert()
        self.assertEqual(report["patch_triangle_counts"],
                         {name: 1 for name in NASAL.values()})
        np.testing.assert_array_equal(mesh.cell_data_dict["gmsh:physical"]["triangle"], [1, 2, 3, 4])
        np.testing.assert_array_equal(mesh.field_data["fluid"], [5, 3])

    def test_incomplete_unknown_or_malformed_mapping_rejected(self):
        for bad in ({7: "nostril_L"}, {**NASAL, 99: "wall"},
                    {**NASAL, 23: "unexpected"}, {**NASAL, 23: []}):
            with self.subTest(mapping=bad), self.assertRaisesRegex(ValueError, "mapping"):
                self.convert(mapping=bad)

    def test_fractional_and_invalid_indices_rejected(self):
        for faces in (FACES.astype(float) + .1, np.where(FACES == 0, -1, FACES), FACES + 99):
            with self.subTest(faces=faces), self.assertRaises(ValueError):
                self.convert(triangles=faces)

    def test_duplicate_missing_or_internal_surface_rejected(self):
        for faces, desc in ((np.r_[FACES, FACES[:1]], DESCRIPTORS + [7]),
                            (FACES[:3], DESCRIPTORS[:3]),
                            (np.array([[0, 1, 1], *FACES[1:]]), DESCRIPTORS)):
            with self.subTest(faces=faces), self.assertRaises(ValueError):
                self.convert(triangles=faces, descriptors=desc)

    def test_zero_volume_and_nonfinite_geometry_rejected(self):
        for points in (POINTS * [1, 1, 0], POINTS + np.nan):
            with self.subTest(points=points), self.assertRaises(ValueError):
                self.convert(points=points)

    def test_negative_tet_orientation_is_corrected(self):
        mesh, _ = self.convert(tetrahedra=TETS[:, [1, 0, 2, 3]])
        xyz = mesh.points[mesh.cells_dict["tetra"][0]]
        self.assertGreater(np.dot(np.cross(xyz[1]-xyz[0], xyz[2]-xyz[0]), xyz[3]-xyz[0]), 0)

    def test_repair_preserves_nasal_and_tube_labels_and_volume(self):
        for profile, mapping, volume_tag in (("nasal", NASAL, 5), ("tube", TUBE, 4)):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as tmp:
                source, target = Path(tmp) / "input.msh", Path(tmp) / "repaired.msh"
                mesh, _ = self.convert(profile=profile, mapping=mapping)
                meshio.write(source, mesh, file_format="gmsh22", binary=False)
                report = repair(source, target)
                output = meshio.read(target)
                self.assertEqual(report["split_cells"], 1)
                self.assertEqual(report["output_cells"], 4)
                self.assertLessEqual(report["relative_volume_change"], 1e-12)
                np.testing.assert_array_equal(output.points[:4], mesh.points)
                np.testing.assert_array_equal(output.cells_dict["triangle"], FACES)
                np.testing.assert_array_equal(output.cell_data_dict["gmsh:physical"]["triangle"],
                                              mesh.cell_data_dict["gmsh:physical"]["triangle"])
                self.assertEqual(set(output.cell_data_dict["gmsh:physical"]["tetra"]), {volume_tag})

    def test_repair_does_not_overwrite_existing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "input.msh", Path(tmp) / "repaired.msh"
            mesh, _ = self.convert()
            meshio.write(source, mesh, file_format="gmsh22", binary=False)
            target.with_suffix(".repair.json").write_text("preserved", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "previous results"):
                repair(source, target)
            self.assertFalse(target.exists())
            self.assertEqual(target.with_suffix(".repair.json").read_text(), "preserved")


if __name__ == "__main__":
    unittest.main()
