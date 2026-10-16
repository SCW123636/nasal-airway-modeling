"""T-062 诊断探针：在 b15（T-058 扩展域）上验证自然分流 BC 的物理自洽性。

策略：以生产 50:50 收敛解（600/）为初场，入口压力设为与 50:50 相同的面积加权
静压（17.114 Pa），跑 150 步。若 BC 正确，总流量应稳定在 ~250 mL/s；
若流量飞走，则 BC 语义在此网格上失效。

用法（WSL 原生，先 source OpenFOAM bashrc）：
  python3 probe_setup.py --case /home/lenovo2/t062_probe/b15_p17 --pressure-pa 17.114 --end-time 150
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
    ap.add_argument("--end-time", type=int, default=150)
    ap.add_argument("--write-interval", type=int, default=50)
    args = ap.parse_args()

    sys.path.insert(0, LIB)
    from openfoam_pressure_adapter import set_pressure_boundaries  # noqa

    case = Path(args.case)
    set_pressure_boundaries(case, float(args.pressure_pa), args.rho, INLETS, OUTLET)

    cd = case / "system/controlDict"
    text = cd.read_text()
    text = re.sub(r"\bendTime\s+[-+\d.eE]+;", "endTime %d;" % args.end_time, text)
    text = re.sub(r"\bwriteInterval\s+[-+\d.eE]+;", "writeInterval %d;" % args.write_interval, text)
    text = re.sub(r"\bpurgeWrite\s+\d+;", "purgeWrite 0;", text)
    # residualControl 强制跑到 endTime（不因残差提前停）
    cd.write_text(text, encoding="ascii")

    p = (case / "0/p").read_text()
    print("inlet p (kinematic) =", re.search(r"nostril_L\s*\{\s*type fixedValue; value uniform ([\d.eE+-]+);", p).group(1))
    print("endTime ->", args.end_time)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
