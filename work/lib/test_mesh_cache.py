"""Unit tests for the 小隼-native mesh cache (windcatcher design port).

Exercises the parts that matter: backend identity, content-signature
sensitivity (geometry + snappyHexMesh change the signature; a pure controlDict
endTime change must NOT), and the reuse contract (no manifest => not reusable,
failed checkMesh never recorded, Mesh-OK record then reusable, edited input
invalidates reuse).
"""
import importlib.util
import json
import re
from pathlib import Path
import tempfile
import unittest

_path = Path(__file__).resolve().parents[1] / '07_cfd_pipeline' / 'solver' / 'mesh_cache.py'
_spec = importlib.util.spec_from_file_location('mesh_cache_test', _path)
mc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mc)


def write_dict(root, name, body):
    (root / 'system').mkdir(parents=True, exist_ok=True)
    (root / 'system' / name).write_text(
        "FoamFile { version 2.0; format ascii; class dictionary; object %s; }\n%s\n" % (name, body),
        encoding='ascii')


def make_case(root, stl=None):
    if stl is None:
        stl = ("solid s\n facet normal 0 0 1\n  outer loop\n"
               "   vertex 0 0 0\n   vertex 1 0 0\n   vertex 0 1 0\n  endloop\n endfacet\nendsolid s\n")
    (root / 'constant' / 'triSurface').mkdir(parents=True, exist_ok=True)
    (root / 'constant' / 'triSurface' / 'nasal.stl').write_text(stl, encoding='ascii')
    write_dict(root, 'blockMeshDict', "maxGlobalCells 3000000;")
    write_dict(root, 'snappyHexMeshDict', "castellatedMeshControls { maxGlobalCells 3000000; }")
    write_dict(root, 'fvSchemes', "ddtSchemes { default Euler; }")
    write_dict(root, 'fvSolution', "solvers { p { solver PCG; } }")
    write_dict(root, 'controlDict', "endTime 1000;")
    (root / 'constant' / 'polyMesh').mkdir(parents=True, exist_ok=True)
    for name in ('points', 'faces', 'owner', 'neighbour', 'boundary'):
        (root / 'constant' / 'polyMesh' / name).write_text("mesh %s\n" % name, encoding='ascii')
    (root / 'log.checkMesh').write_text("Mesh OK.\n", encoding='ascii')
    return root


def completed_mesh_steps():
    return [{"name": "blockMesh", "returncode": 0, "timed_out": False},
            {"name": "snappyHexMesh", "returncode": 0, "timed_out": False},
            {"name": "checkMesh", "returncode": 0, "timed_out": False}]


class BackendIdentityTests(unittest.TestCase):
    def test_deterministic_on_same_machine(self):
        a = mc.detect_backend_identity()
        b = mc.detect_backend_identity()
        self.assertEqual(a, b)
        self.assertEqual(a["name"], "wsl")
        self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", a["installation_sha256"]))
        mc._backend_identity(a)  # must not raise

    def test_rejects_unverifiable_identity(self):
        with self.assertRaises(ValueError):
            mc._backend_identity({"name": "wsl", "version": "v1912", "installation_sha256": "short"})


class SignatureTests(unittest.TestCase):
    def test_signature_sensitive_to_geometry_not_to_endTime(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = make_case(Path(tmp) / 'a')
            b = make_case(Path(tmp) / 'b')
            identity = mc.detect_backend_identity()
            sig_a = mc.mesh_inputs_signature(a, identity)
            sig_b = mc.mesh_inputs_signature(b, identity)
            self.assertTrue(sig_a["valid"])  # guards against silent invalid
            self.assertEqual(sig_a["signature"], sig_b["signature"])
            (a / 'constant' / 'triSurface' / 'nasal.stl').write_text(
                "solid s\n facet normal 0 0 1\n  outer loop\n"
                "   vertex 0 0 0\n   vertex 2 0 0\n   vertex 0 2 0\n  endloop\n endfacet\nendsolid s\n",
                encoding='ascii')
            sig_a2 = mc.mesh_inputs_signature(a, identity)
            self.assertNotEqual(sig_a2["signature"], sig_b["signature"])

    def test_snappyhexmesh_change_alters_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = make_case(Path(tmp) / 'a')
            b = make_case(Path(tmp) / 'b')
            identity = mc.detect_backend_identity()
            write_dict(b, 'snappyHexMeshDict', "castellatedMeshControls { maxGlobalCells 9999999; }")
            sig_a = mc.mesh_inputs_signature(a, identity)
            sig_b = mc.mesh_inputs_signature(b, identity)
            self.assertNotEqual(sig_a["signature"], sig_b["signature"])

    def test_controlDict_endTime_change_keeps_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = make_case(Path(tmp) / 'a')
            identity = mc.detect_backend_identity()
            sig_before = mc.mesh_inputs_signature(a, identity)
            write_dict(a, 'controlDict', "endTime 9999;")
            sig_after = mc.mesh_inputs_signature(a, identity)
            self.assertEqual(sig_before["signature"], sig_after["signature"])


class ReuseTests(unittest.TestCase):
    def test_no_manifest_is_not_reusable(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_case(Path(tmp) / 'c')
            sig = mc.mesh_inputs_signature(c, mc.detect_backend_identity())
            res = mc.inspect_reuse(c, sig)
            self.assertFalse(res["reusable"])

    def test_record_rejects_failed_checkMesh(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_case(Path(tmp) / 'c')
            (c / 'log.checkMesh').write_text("Failed 1 mesh checks.\n", encoding='ascii')
            sig = mc.mesh_inputs_signature(c, mc.detect_backend_identity())
            rec = mc.record_mesh(c, sig, "run-1",
                                 check_result={"returncode": 0, "output": "Failed 1 mesh checks.\n", "timed_out": False},
                                 completed_steps=completed_mesh_steps())
            self.assertFalse(rec["recorded"])

    def test_record_then_reuse_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_case(Path(tmp) / 'c')
            identity = mc.detect_backend_identity()
            sig = mc.mesh_inputs_signature(c, identity)
            rec = mc.record_mesh(c, sig, "run-1",
                                 check_result={"returncode": 0, "output": "Mesh OK.\n", "timed_out": False},
                                 completed_steps=completed_mesh_steps())
            self.assertTrue(rec["recorded"])
            res = mc.inspect_reuse(c, sig)
            self.assertTrue(res["reusable"])
            # Editing an input changes the recomputed signature => reuse must fail.
            (c / 'constant' / 'triSurface' / 'nasal.stl').write_text(
                "solid s\n facet normal 0 0 1\n  outer loop\n"
                "   vertex 0 0 0\n   vertex 2 0 0\n   vertex 0 2 0\n  endloop\n endfacet\nendsolid s\n",
                encoding='ascii')
            new_sig = mc.mesh_inputs_signature(c, identity)
            res2 = mc.inspect_reuse(c, new_sig)
            self.assertFalse(res2["reusable"])


class BlockMeshOnlyTests(unittest.TestCase):
    """小隼 synthetic regression cases are blockMesh-only: no snappyHexMeshDict,
    no triSurface. The cache must still work for them (dictionaries-only signature)."""

    def _blockmesh_case(self, root):
        make_case(root)
        (root / 'system' / 'snappyHexMeshDict').unlink()
        (root / 'constant' / 'triSurface' / 'nasal.stl').unlink()
        return root

    def test_blockmesh_only_signature_is_valid_without_trisurface(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = self._blockmesh_case(Path(tmp) / 'c')
            sig = mc.mesh_inputs_signature(c, mc.detect_backend_identity())
            self.assertTrue(sig["valid"])
            self.assertEqual(sig["evidence"]["geometry"], {})

    def test_snappy_dict_absence_is_part_of_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self._blockmesh_case(Path(tmp) / 'a')
            b = make_case(Path(tmp) / 'b')  # has snappyHexMeshDict + triSurface
            ident = mc.detect_backend_identity()
            sig_a = mc.mesh_inputs_signature(a, ident)
            sig_b = mc.mesh_inputs_signature(b, ident)
            self.assertTrue(sig_a["valid"])
            self.assertTrue(sig_b["valid"])
            self.assertNotEqual(sig_a["signature"], sig_b["signature"])

    def test_record_and_reuse_blockmesh_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = self._blockmesh_case(Path(tmp) / 'c')
            ident = mc.detect_backend_identity()
            sig = mc.mesh_inputs_signature(c, ident)
            rec = mc.record_mesh(c, sig, 'run-bm',
                                 check_result={"returncode": 0, "output": "Mesh OK.\n", "timed_out": False},
                                 completed_steps=[{"name": "blockMesh", "returncode": 0, "timed_out": False},
                                                 {"name": "checkMesh", "returncode": 0, "timed_out": False}])
            self.assertTrue(rec["recorded"])
            self.assertTrue(mc.inspect_reuse(c, sig)["reusable"])


if __name__ == '__main__':
    unittest.main()
