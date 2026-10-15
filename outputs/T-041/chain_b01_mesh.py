"""Wait for the b15 solve (CPU-exclusive lane), then build the b01 volume mesh
with Slicer's CFD Mesh Generator (Netgen engine).

Serial by construction: the 317-step interruption happened because meshing ran
concurrently with the solver. This script will NOT start meshing until no
simpleFoam process exists.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

WSL = ["wsl.exe", "-d", "Ubuntu-22.04", "--"]
SLICER = r"D:\项目\鼻腔建模\软件\slicer\3D Slicer 5.12.4\Slicer.exe"
MESHER = r"D:\项目\鼻腔建模\outputs\T-039\run_mesher_generic.py"
JOB = r"D:\项目\鼻腔建模\outputs\T-041\b01_job_netgen.json"


def wsl(script, t=60):
    return subprocess.run(WSL + ["bash", "-c", script], capture_output=True, text=True, timeout=t)


print("step 1: wait for b15 simpleFoam to finish ...", flush=True)
for _ in range(720):          # up to ~12 h
    r = wsl("pgrep -x simpleFoam >/dev/null && echo RUNNING || echo DONE")
    if "DONE" in r.stdout:
        print("b15 finished", flush=True)
        break
    time.sleep(60)
else:
    print("TIMEOUT waiting for b15; aborting meshing to protect the CPU lane", flush=True)
    sys.exit(1)

print("step 2: Slicer CFD Mesh Generator (netgen) on b01 ...", flush=True)
env = dict(os.environ)
env["T039_JOB"] = JOB
r = subprocess.run([SLICER, "--no-splash", "--no-main-window", "--testing",
                    "--python-script", MESHER],
                   capture_output=True, text=True, env=env, timeout=7200)
print("slicer rc =", r.returncode, flush=True)
print((r.stdout or "")[-3000:], flush=True)
print((r.stderr or "")[-1500:], flush=True)

out = Path(r"D:\项目\鼻腔建模\outputs\T-041\b01_netgen")
print("step 3: report artifacts", flush=True)
for p in sorted(out.rglob("*")) if out.exists() else []:
    if p.is_file():
        print("  ", p.relative_to(out), p.stat().st_size, flush=True)
print("DONE", flush=True)
