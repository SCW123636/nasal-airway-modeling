# -*- coding: utf-8 -*-
"""T-046 判据 C4：flow_streamlines 钩子行为测试（合成场，不碰真实数据）。"""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

import flow_streamlines as fs


def make_duct_vtk(vtk_dir):
    """直管道：x,z ∈ [0,0.01]，y ∈ [0,0.05]；2×3×2 节点、两格 12 四面体；U=(0,0.5,0)。"""
    nx, ny, nz = 2, 3, 2
    xs = np.linspace(0, 0.01, nx)
    ys = np.linspace(0, 0.05, ny)
    zs = np.linspace(0, 0.01, nz)
    pts = np.array([(x, y, z) for y in ys for z in zs for x in xs])
    def idx(i, j, k):
        return j * (nz * nx) + k * nx + i
    corners = [idx(0, 0, 0), idx(1, 0, 0), idx(0, 1, 0), idx(1, 1, 0),
               idx(0, 0, 1), idx(1, 0, 1), idx(0, 1, 1), idx(1, 1, 1)]
    conn = []
    for base in (corners, [c + nx * nz for c in corners]):
        conn += [(base[0], base[1], base[3], base[7]), (base[0], base[3], base[2], base[7]),
                 (base[0], base[2], base[6], base[7]), (base[0], base[6], base[4], base[7]),
                 (base[0], base[4], base[5], base[7]), (base[0], base[5], base[1], base[7])]
    conn = np.array(conn)
    U = np.tile(np.array([[0.0, 0.5, 0.0]]), (len(pts), 1))
    p = np.zeros(len(pts))

    def flat(a):
        return " ".join(repr(float(v)) for v in np.asarray(a).reshape(-1))

    (vtk_dir / "internal.vtu").write_text(
        "<VTKFile type='UnstructuredGrid' version='0.1' byte_order='LittleEndian'>"
        "<UnstructuredGrid><Piece NumberOfPoints='%d' NumberOfCells='%d'>"
        "<PointData>"
        "<DataArray Name='U' NumberOfComponents='3' type='Float32'>%s</DataArray>"
        "<DataArray Name='p' type='Float32'>%s</DataArray>"
        "</PointData>"
        "<Points><DataArray Name='Points' NumberOfComponents='3' type='Float32'>%s</DataArray></Points>"
        "<Cells>"
        "<DataArray Name='connectivity' type='Int32'>%s</DataArray>"
        "<DataArray Name='offsets' type='Int32'>%s</DataArray>"
        "<DataArray Name='types' type='UInt8'>%s</DataArray>"
        "</Cells></Piece></UnstructuredGrid></VTKFile>"
        % (len(pts), len(conn), flat(U), flat(p), flat(pts), flat(conn),
           " ".join(str(4 * (i + 1)) for i in range(len(conn))),
           " ".join("10" for _ in range(len(conn)))), encoding="utf-8")

    def vtp(name, ppts, tris):
        (vtk_dir / (name + ".vtp")).write_text(
            "<VTKFile type='PolyData' version='0.1' byte_order='LittleEndian'>"
            "<PolyData><Piece NumberOfPoints='%d' NumberOfPolys='%d'>"
            "<Points><DataArray Name='Points' NumberOfComponents='3' type='Float32'>%s</DataArray></Points>"
            "<Polys>"
            "<DataArray Name='connectivity' type='Int32'>%s</DataArray>"
            "<DataArray Name='offsets' type='Int32'>%s</DataArray>"
            "</Polys></Piece></PolyData></VTKFile>"
            % (len(ppts), len(tris), flat(ppts), flat(tris),
               " ".join(str(3 * (i + 1)) for i in range(len(tris)))), encoding="utf-8")

    # 入口 y=0 分左/右两半（各 4×7 节点），出口 y=0.05 整面 7×7 节点
    # （密度保证出口判定阈值 1.2mm 内必有节点），壁面给侧面示意
    def grid(x0, x1, y, n_x=7, n_z=7):
        xs_g = np.linspace(x0, x1, n_x)
        zs_g = np.linspace(0, 0.01, n_z)
        pts_g = np.array([(x, y, z) for z in zs_g for x in xs_g])
        tris_g = []
        for j in range(n_z - 1):
            for i in range(n_x - 1):
                a = j * n_x + i
                tris_g += [(a, a + 1, a + n_x), (a + 1, a + n_x + 1, a + n_x)]
        return pts_g, tris_g

    L, Lt = grid(0, 0.005, 0, n_x=4)
    R, Rt = grid(0.005, 0.01, 0, n_x=4)
    O, Ot = grid(0, 0.01, 0.05)
    W = np.array([(0, 0, 0), (0, 0.05, 0), (0, 0, 0.01), (0, 0.05, 0.01),
                  (0.01, 0, 0), (0.01, 0.05, 0), (0.01, 0, 0.01), (0.01, 0.05, 0.01)])
    vtp("nostril_L", L, Lt)
    vtp("nostril_R", R, Rt)
    vtp("nasopharynx_outlet", O, Ot)
    vtp("wall", W, [(0, 1, 2), (1, 3, 2), (4, 5, 6), (5, 7, 6)])


def minimal_context():
    return {"title": "t", "crumb": "c", "sub": "s",
            "badges": [("warn", "未收敛")],
            "honesty_summary": "summary", "honesty": ["h1"],
            "stats": [("k", "v", "")], "facts": [("f", "v")], "footnote": "fn"}


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="flow_sl_")
        self.root = Path(self.tmp.name)
        self.vtk = self.root / "vtk"
        self.vtk.mkdir()
        make_duct_vtk(self.vtk)

    def tearDown(self):
        self.tmp.cleanup()

    def test_extract_field_shapes(self):
        f = fs.extract_field(self.vtk)
        self.assertEqual(f["conn"].shape, (12, 4))
        self.assertEqual(f["U"].shape, (12, 3))
        self.assertEqual(f["nostril_L_tri"].shape, (36, 3))  # 4×7 网格 → 3×6×2 三角

    def test_build_uniform_duct_reaches_outlet(self):
        meta = fs.build_streamlines(self.vtk, self.root / "s.html", self.root / "s.json",
                                    minimal_context())
        self.assertGreater(meta["n_lines"], 0)
        self.assertEqual(meta["reasons"].get("reached_outlet", 0), meta["n_lines"])
        html = (self.root / "s.html").read_text(encoding="utf-8")
        self.assertNotIn("__TITLE__", html)
        self.assertIn("streamline", html.lower() + "streamline")
        self.assertIn("<canvas id=\"hist\"", html)

    def test_non_tet_rejected(self):
        bad = self.root / "bad"
        bad.mkdir()
        make_duct_vtk(bad)
        text = (bad / "internal.vtu").read_text(encoding="utf-8")
        (bad / "internal.vtu").write_text(text.replace("10", "12"), encoding="utf-8")
        with self.assertRaises(ValueError):
            fs.extract_field(bad)


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="flow_sl_job_")
        self.root = Path(self.tmp.name)
        self.directory = self.root / "job"
        self.export = self.directory / "export" / "s_test"
        vtk_dir = self.export / "case" / "VTK" / "case"
        vtk_dir.mkdir(parents=True)
        make_duct_vtk(vtk_dir)
        self.vtk_dir = vtk_dir
        self.data = {"id": "s_test", "case_id": "p0",
                     "result": {"numerical_validation": "unchecked", "scenarios": {}}}
        self.assets = []

    def tearDown(self):
        self.tmp.cleanup()

    def asset(self, name, path, label):
        path = Path(path)
        self.assertTrue(str(path).startswith(str(self.directory)))
        self.assets.append((name, path.name, label))

    def test_no_vtu(self):
        empty = self.root / "empty"
        empty.mkdir()
        out = fs.export_job_streamlines(self.directory, self.data, self.asset, empty)
        self.assertEqual(out["status"], "no_vtu")
        self.assertEqual(self.assets, [])

    def test_missing_patches(self):
        for f in self.vtk_dir.glob("*.vtp"):
            f.unlink()
        out = fs.export_job_streamlines(self.directory, self.data, self.asset, self.export)
        self.assertEqual(out["status"], "missing_patches")
        self.assertEqual(sorted(out["missing"]), sorted(fs.PATCH_FILES))
        self.assertEqual(self.assets, [])

    def test_generated_and_registered(self):
        out = fs.export_job_streamlines(self.directory, self.data, self.asset, self.export)
        self.assertEqual(out["status"], "generated")
        self.assertGreater(out["n_lines"], 0)
        names = sorted(n for n, _, _ in self.assets)
        self.assertEqual(names, ["streamlines.html", "streamlines_meta.json"])
        html = (self.directory / "streamlines.html").read_text(encoding="utf-8")
        self.assertIn("s_test", html)          # job id 进页面
        self.assertIn("未收敛", html)           # 诚实声明随 validation=unchecked
        meta = json.loads((self.directory / "streamlines_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["reasons"].get("reached_outlet"), meta["n_lines"])


if __name__ == "__main__":
    unittest.main()
