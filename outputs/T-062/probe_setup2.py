"""T-062 诊断探针 v2：参数化求解器设置，定位自然分流 BC 在 b15 网格上的发散根因。

背景：以生产 50:50 收敛解（600/）为初场、入口压力设为同一 Δp（17.114 Pa）时，
解仍缓慢发散（Ux 残差 0.0014 -> 0.029，60 迭代）。T-021 合成案例同 BC 同
`consistent yes` 却收敛，差异在 `nNonOrth`/`relTol`/网格质量。

用法（WSL 原生，先 source OpenFOAM bashrc）：
  python3 probe_setup2.py --case DIR --pressure-pa 17.114 --end-time 100 \
      --consistent no --reltol 0
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

LIB = "/mnt/d/项目/鼻腔建模/work/lib"
INLETS = ("nostril_L", "nostril_R")
OUTLET = "oropharynx_truncation_outlet"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--pressure-pa", type=float, required=True)
    ap.add_argument("--rho", type=float, default=1.2)
    ap.add_argument("--end-time", type=int, default=100)
    ap.add_argument("--write-interval", type=int, default=50)
    ap.add_argument("--consistent", choices=["yes", "no"], default=None)
    ap.add_argument("--reltol", type=float, default=None)
    ap.add_argument("--nonorth", type=int, default=None)
    ap.add_argument("--u-relax", type=float, default=None)
    ap.add_argument("--p-relax", type=float, default=None)
    args = ap.parse_args()

    sys.path.insert(0, LIB)
    from openfoam_pressure_adapter import set_pressure_boundaries  # noqa

    case = Path(args.case)

    # controlDict：改写 endTime/writeInterval/purgeWrite（在 set_pressure_boundaries 前，
    # 以便其函数块注入基于同一文本）
    cd = case / "system/controlDict"
    text = cd.read_text()
    text = re.sub(r"\bendTime\s+[-+\d.eE]+;", "endTime %d;" % args.end_time, text)
    text = re.sub(r"\bwriteInterval\s+[-+\d.eE]+;", "writeInterval %d;" % args.write_interval, text)
    text = re.sub(r"\bpurgeWrite\s+\d+;", "purgeWrite 0;", text)
    cd.write_text(text, encoding="ascii")

    set_pressure_boundaries(case, float(args.pressure_pa), args.rho, INLETS, OUTLET)

    # fvSolution 变体
    fs = case / "system/fvSolution"
    sol = fs.read_text()
    if args.consistent is not None:
        sol = re.sub(r"\bconsistent\s+\w+;", "consistent %s;" % args.consistent, sol)
    if args.nonorth is not None:
        sol = re.sub(r"\bnNonOrthogonalCorrectors\s+\d+;",
                     "nNonOrthogonalCorrectors %d;" % args.nonorth, sol)
    if args.reltol is not None:
        sol = re.sub(r"\brelTol\s+[-+\d.eE]+;", "relTol %g;" % args.reltol, sol)
    if args.u_relax is not None:
        sol = re.sub(r"(equations\s*\{\s*U\s+)[-+\d.eE]+(;)", r"\g<1>%g\g<2>" % args.u_relax, sol)
    if args.p_relax is not None:
        sol = re.sub(r"(fields\s*\{\s*p\s+)[-+\d.eE]+(;)", r"\g<1>%g\g<2>" % args.p_relax, sol)
    fs.write_text(sol, encoding="ascii")

    p = (case / "0/p").read_text()
    m = re.search(r"nostril_L\s*\{\s*type fixedValue; value uniform ([\d.eE+-]+);", p)
    print("case=%s inlet_p_kin=%s endTime=%d consistent=%s reltol=%s nonorth=%s"
          % (args.case, m.group(1) if m else "?", args.end_time,
             args.consistent, args.reltol, args.nonorth))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
