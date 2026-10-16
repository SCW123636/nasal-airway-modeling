# -*- coding: utf-8 -*-
"""run_mca_t059.py —— 对 T-059 批跑的 auto_pass 例逐例运行 measure_mca.py。

measure_mca.py 输入（本驱动显式绑定，不用其默认路径）：
- --mask       outputs/T-059/surfaces/bXX/air_mask.nii.gz（T-058 起生产链保存的气域掩膜）
- --labels-dir C:/ts_work/bXX/masks（TS 四标签；左右容积比同样按语义标签）
- --landmarks  work/06_auto_landmarks/bXX/landmarks.json
- --out-dir    outputs/T-059/mca

b20 跳过（T-059 已 escalate：landmark 缺 nostril_L 提案，真因另立卡）。
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "work/lib"
PY = sys.executable

SKIP = {"b20"}  # T-059 escalated 例（上游 landmark 缺口，非本步骤可修）


def main() -> int:
    surf = ROOT / "outputs/T-059/surfaces"
    out_d = ROOT / "outputs/T-059/mca"
    out_d.mkdir(parents=True, exist_ok=True)
    cases = sorted(p.name for p in surf.iterdir()
                   if p.is_dir() and p.name.startswith("b") and p.name not in SKIP)
    ok, fail = 0, []
    for c in cases:
        air = surf / c / "air_mask.nii.gz"
        cmd = [PY, "-u", str(LIB / "measure_mca.py"), "--case", c,
               "--mask", str(air),
               "--labels-dir", rf"C:\ts_work\{c}\masks",
               "--landmarks", str(ROOT / "work/06_auto_landmarks" / c / "landmarks.json"),
               "--ct", rf"C:\ts_work\{c}\ct.nii.gz",
               "--out-dir", str(out_d)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0 and (out_d / f"mca_{c}.json").exists():
            ok += 1
            print(f"{c}: OK")
        else:
            fail.append(c)
            print(f"{c}: FAIL rc={r.returncode}")
            print((r.stderr or r.stdout)[-500:])
    print(f"\nMCA done: {ok} ok, {len(fail)} fail {fail}")
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
