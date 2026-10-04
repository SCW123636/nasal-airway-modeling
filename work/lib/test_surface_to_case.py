"""Synthetic surface_to_case tests: toy square-pipe geometry only, never patient data."""
import json
from pathlib import Path
import re
import tempfile
import unittest

import surface_to_case as s2c


def toy_pipe_stl(path, extra_solid=False):
    """10 mm long square pipe, 2x2 mm cross-section, axis +x; solids in mm."""
    def quad(a, b, c, d):
        return [a, b, c, a, c, d]
    solids = {
        "inlet": quad((0, 0, 0), (0, 0, 2), (0, 2, 2), (0, 2, 0)),
        "outlet": quad((10, 0, 0), (10, 2, 2), (10, 0, 2), (10, 2, 0)),
        "wall": (quad((0, 0, 0), (10, 0, 0), (10, 2, 0), (0, 2, 0))
                 + quad((0, 0, 2), (0, 2, 2), (10, 2, 2), (10, 0, 2))
                 + quad((0, 0, 0), (0, 0, 2), (10, 0, 2), (10, 0, 0))
                 + quad((0, 2, 0), (10, 2, 0), (10, 2, 2), (0, 2, 2))),
    }
    if extra_solid:
        solids["mystery"] = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    lines = []
    for name, vertices in solids.items():
        lines.append("solid " + name)
        for i in range(0, len(vertices), 3):
            lines.append(" facet normal 0 0 0")
            lines.append("  outer loop")
            for v in vertices[i:i + 3]:
                lines.append("   vertex %s %s %s" % v)
            lines.append("  endloop")
            lines.append(" endfacet")
        lines.append("endsolid " + name)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def toy_patch_map(path):
    path.write_text(json.dumps({"inlet": "inlet", "outlet": "outlet", "wall": "wall"}), encoding="utf-8")


EXPECTED_FILES = ["0/p", "0/U", "constant/transportProperties", "constant/turbulenceProperties",
                  "constant/triSurface/inlet.stl", "constant/triSurface/outlet.stl",
                  "constant/triSurface/wall.stl", "system/controlDict", "system/fvSchemes",
                  "system/fvSolution", "system/blockMeshDict", "system/snappyHexMeshDict",
                  "case_manifest.json"]


def run_s1(tmp, out_name="case", extra_solid=False):
    root = Path(tmp)
    stl = root / "toy.stl"
    toy_pipe_stl(stl, extra_solid=extra_solid)
    patch_map = root / "map.json"
    toy_patch_map(patch_map)
    argv = ["--surface", str(stl), "--patch-map", str(patch_map), "--out", str(root / out_name),
            "--location-in-mesh", "5 1 1", "--dry-run"]
    s2c.main(argv)
    return root / out_name


class SurfaceToCaseTests(unittest.TestCase):
    def test_case_files_complete_and_convert_marker(self):
        with tempfile.TemporaryDirectory(prefix="s2c_test_") as tmp:
            case = run_s1(tmp)
            for rel in EXPECTED_FILES:
                self.assertTrue((case / rel).is_file(), "missing " + rel)
            blockmesh = (case / "system/blockMeshDict").read_text(encoding="ascii")
            self.assertIn("convertToMeters 0.001", blockmesh)
            manifest = json.loads((case / "case_manifest.json").read_text(encoding="utf-8"))
            for rel, sha in manifest["files_sha256"].items():
                self.assertEqual(sha, s2c.sha256_bytes((case / rel).read_bytes()), rel)

    def test_snappy_patches_all_in_patch_map(self):
        with tempfile.TemporaryDirectory(prefix="s2c_test_") as tmp:
            case = run_s1(tmp)
            text = (case / "system/snappyHexMeshDict").read_text(encoding="ascii")
            geometry = set(re.findall(r"(\w+) \{ type triSurfaceMesh;", text))
            refinement = set(re.findall(r"^\s+(\w+) \{ level \(", text, re.MULTILINE))
            self.assertEqual(geometry, {"inlet", "outlet", "wall"})
            self.assertEqual(refinement, {"inlet", "outlet", "wall"})

    def test_unmapped_solid_fails(self):
        with tempfile.TemporaryDirectory(prefix="s2c_test_") as tmp:
            with self.assertRaises(SystemExit) as ctx:
                run_s1(tmp, extra_solid=True)
            self.assertNotEqual(ctx.exception.code, 0)

    def test_overwrite_protection(self):
        with tempfile.TemporaryDirectory(prefix="s2c_test_") as tmp:
            run_s1(tmp)
            with self.assertRaises(SystemExit) as ctx:
                run_s1(tmp)
            self.assertNotEqual(ctx.exception.code, 0)

    def test_determinism_except_timestamp(self):
        with tempfile.TemporaryDirectory(prefix="s2c_test_") as tmp:
            case_a = run_s1(tmp, "case_a")
            case_b = run_s1(tmp, "case_b")
            manifest_a = json.loads((case_a / "case_manifest.json").read_text(encoding="utf-8"))
            manifest_b = json.loads((case_b / "case_manifest.json").read_text(encoding="utf-8"))
            manifest_a.pop("generated_at")
            manifest_b.pop("generated_at")
            self.assertEqual(manifest_a, manifest_b)
            strip = lambda p: re.sub(r'^\s+"generated_at".*\n', "", p.read_text(encoding="utf-8"),
                                     flags=re.MULTILINE)
            self.assertEqual(strip(case_a / "case_manifest.json"), strip(case_b / "case_manifest.json"))

    def test_trisurface_written_in_meters(self):
        with tempfile.TemporaryDirectory(prefix="s2c_test_") as tmp:
            case = run_s1(tmp)
            text = (case / "constant/triSurface/inlet.stl").read_text(encoding="ascii")
            coords = [float(v) for v in re.findall(r"vertex\s+(\S+)\s+\S+\s+\S+", text)]
            self.assertTrue(coords)
            self.assertLess(max(coords), 0.011)  # 10 mm -> 0.01 m, never 10 (mm leak)


if __name__ == "__main__":
    unittest.main()
