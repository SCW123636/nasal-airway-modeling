"""Synthetic extract_cfd_metrics tests: fabricated VTP/VTU fixtures only, never patient data."""
import json
from pathlib import Path
import tempfile
import unittest

import extract_cfd_metrics as ecm

VERIFIED_CASE = (Path(__file__).resolve().parents[1] / "07_cfd_pipeline" / "solver_reference"
                 / "results" / "poiseuille_v1912_verified" / "medium")
VERIFIED_DELTA_P = 0.21587924916228


def vtp_patch(points, faces, p, u):
    connectivity = " ".join(str(i) for f in faces for i in f)
    offsets = " ".join(str(sum(len(f) for f in faces[:k + 1])) for k in range(len(faces)))
    coords = " ".join("%g %g %g" % v for v in points)
    pvals = " ".join("%g" % v for v in p)
    uvals = " ".join("%g %g %g" % v for v in u)
    return f"""<?xml version='1.0'?>
<VTKFile type='PolyData' version='0.1' byte_order='LittleEndian'>
 <PolyData><Piece NumberOfPoints='{len(points)}' NumberOfPolys='{len(faces)}'>
  <Points><DataArray type='Float32' NumberOfComponents='3' format='ascii'>{coords}</DataArray></Points>
  <Polys>
   <DataArray type='Int32' Name='connectivity' format='ascii'>{connectivity}</DataArray>
   <DataArray type='Int32' Name='offsets' format='ascii'>{offsets}</DataArray>
  </Polys>
  <CellData>
   <DataArray type='Float32' Name='p' format='ascii'>{pvals}</DataArray>
   <DataArray type='Float32' Name='U' NumberOfComponents='3' format='ascii'>{uvals}</DataArray>
  </CellData>
 </Piece></PolyData>
</VTKFile>
"""


def square_patch(x, y0, y1, z0, z1, p, speed):
    points = [(x, y0, z0), (x, y1, z0), (x, y1, z1), (x, y0, z1)]
    faces = [[0, 1, 2], [0, 2, 3]]
    return vtp_patch(points, faces, [p, p], [(speed, 0, 0), (speed, 0, 0)])


def internal_vtu():
    points = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
              (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
              (2, 0, 0), (2, 1, 0), (2, 0, 1), (2, 1, 1)]
    cells = [list(range(8)), [1, 8, 9, 2, 5, 10, 11, 6]]
    connectivity = " ".join(str(i) for c in cells for i in c)
    coords = " ".join("%g %g %g" % v for v in points)
    return f"""<?xml version='1.0'?>
<VTKFile type='UnstructuredGrid' version='0.1' byte_order='LittleEndian'>
 <UnstructuredGrid><Piece NumberOfPoints='{len(points)}' NumberOfCells='2'>
  <Points><DataArray type='Float32' NumberOfComponents='3' format='ascii'>{coords}</DataArray></Points>
  <Cells>
   <DataArray type='Int32' Name='connectivity' format='ascii'>{connectivity}</DataArray>
   <DataArray type='Int32' Name='offsets' format='ascii'>8 16</DataArray>
   <DataArray type='UInt8' Name='types' format='ascii'>12 12</DataArray>
  </Cells>
  <CellData>
   <DataArray type='Float32' Name='p' format='ascii'>1.5 0.5</DataArray>
   <DataArray type='Float32' Name='U' NumberOfComponents='3' format='ascii'>3 4 0  0 0 12</DataArray>
  </CellData>
 </Piece></UnstructuredGrid>
</VTKFile>
"""


def make_case(root):
    case = Path(root) / "case"
    boundary = case / "VTK" / "case_100" / "boundary"
    boundary.mkdir(parents=True)
    (case / "VTK" / "case_100" / "internal.vtu").write_text(internal_vtu(), encoding="ascii")
    (boundary / "nostril_L.vtp").write_text(square_patch(0, 0, 1, 0, 1, 2.0, 0.1), encoding="ascii")
    (boundary / "nostril_R.vtp").write_text(square_patch(0, 0, 3, 0, 1, 2.0, 0.1), encoding="ascii")
    (boundary / "nasopharynx.vtp").write_text(square_patch(1, 0, 4, 0, 1, 0.0, 0.1), encoding="ascii")
    (boundary / "wall.vtp").write_text(square_patch(0, 0, 1, 1, 2, 0.0, 0.0), encoding="ascii")
    (case / "log.simpleFoam").write_text("SIMPLE solution converged in 100 iterations\n",
                                         encoding="ascii")
    (case / "case_manifest.json").write_text(json.dumps({
        "patch_map": {"nostril_L": "inlet", "nostril_R": "inlet",
                      "nasopharynx": "outlet", "wall": "wall"}}), encoding="utf-8")
    return case


class ExtractMetricsTests(unittest.TestCase):
    def test_metric_identities_on_synthetic_fixture(self):
        with tempfile.TemporaryDirectory(prefix="ecm_test_") as tmp:
            metrics = ecm.extract(make_case(tmp))["metrics"]
            self.assertAlmostEqual(metrics["delta_p_pa"]["value"], 2.4)  # 1.2 * (2.0 - 0.0)
            self.assertAlmostEqual(metrics["total_flow_m3s"]["value"], 0.4)  # 0.1*1 + 0.1*3
            self.assertAlmostEqual(metrics["split_ratio"]["value"], 0.25)
            self.assertAlmostEqual(metrics["symmetry_phi"]["value"], 1.0 / 3.0)
            self.assertEqual(metrics["mass_imbalance_frac"], 0.0)
            self.assertAlmostEqual(metrics["max_velocity_mps"]["value"], 12.0)
            self.assertAlmostEqual(metrics["resistance_R"]["value_pa_s_m3"], 6.0)
            self.assertAlmostEqual(metrics["resistance_R"]["value_pa_s_ml"], 6e-6)
            self.assertTrue(metrics["converged"])
            self.assertEqual(metrics["magnitude_check"]["value"], "outside")

    def test_honesty_semantics(self):
        with tempfile.TemporaryDirectory(prefix="ecm_test_") as tmp:
            metrics = ecm.extract(make_case(tmp))["metrics"]
            self.assertEqual(metrics["region_flow_fraction"]["status"], "not_computed")
            self.assertEqual(metrics["turbulence_intensity"]["report_status"], "not_applicable")
            self.assertEqual(metrics["nasal_valve_peak_mps"]["status"], "not_computed")
            self.assertEqual(metrics["wall_shear_force_n"]["status"], "not_computed")

    def test_valve_slice_peak(self):
        with tempfile.TemporaryDirectory(prefix="ecm_test_") as tmp:
            # Cell 0 centroid x=0.5 (|U|=5), cell 1 centroid x=1.5 (|U|=12), units metres.
            metrics = ecm.extract(make_case(tmp), valve_slice=(0, 0.5), valve_slab_mm=200.0)
            valve = metrics["metrics"]["nasal_valve_peak_mps"]
            self.assertAlmostEqual(valve["value_mps"], 5.0)
            self.assertEqual(valve["cells_in_slab"], 1)

    def test_missing_vtk_fails_without_partial_json(self):
        with tempfile.TemporaryDirectory(prefix="ecm_test_") as tmp:
            case = make_case(tmp)
            for path in (case / "VTK").rglob("*"):
                pass
            import shutil
            shutil.rmtree(case / "VTK")
            with self.assertRaises(SystemExit) as ctx:
                ecm.extract(case)
            self.assertNotEqual(ctx.exception.code, 0)

    def test_verified_case_regression(self):
        if not (VERIFIED_CASE / "VTK").is_dir():
            self.skipTest("verified reference case not present")
        metrics = ecm.extract(VERIFIED_CASE)["metrics"]
        self.assertLess(abs(metrics["delta_p_pa"]["value"] - VERIFIED_DELTA_P)
                        / VERIFIED_DELTA_P, 0.01)
        self.assertLess(metrics["mass_imbalance_frac"], 1e-6)
        self.assertTrue(metrics["converged"])
        self.assertEqual(metrics["split_ratio"]["status"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
