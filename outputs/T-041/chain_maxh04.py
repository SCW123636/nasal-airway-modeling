"""Wait for the b15 maxh1 S-A run to finish, then run the maxh04 S-A cell.

CPU lane is exclusive: only one solver at a time.
"""
import subprocess
import sys
import time

WSL = ["wsl.exe", "-d", "Ubuntu-22.04", "--"]
CASE2 = "/home/lenovo2/patient_cfd/t001b_maxh04/foam_repaired"


def sh(a, t=300000):
    return subprocess.run(WSL + ["bash", "-c", a], capture_output=True, text=True, timeout=t)


print("waiting for maxh1 simpleFoam to finish ...", flush=True)
for _ in range(600):          # up to ~10 h
    r = sh("pgrep -x simpleFoam >/dev/null && echo RUNNING || echo DONE", 60)
    if "DONE" in r.stdout:
        print("maxh1 finished", flush=True)
        break
    time.sleep(60)
else:
    print("TIMEOUT waiting for maxh1", flush=True)
    sys.exit(1)

print("--- launching maxh04 S-A ---", flush=True)
r = sh("cd %s && source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1 "
       "&& simpleFoam > log.simpleFoam 2>&1; echo RC=$?" % CASE2)
print(r.stdout[-600:], flush=True)
print("DONE", flush=True)
