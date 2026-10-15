import re
import subprocess

WSL = ["wsl.exe", "-d", "Ubuntu-22.04", "--"]
CASE = "/home/lenovo2/patient_cfd/b15_maxh1"


def cat(rel):
    r = subprocess.run(WSL + ["cat", "%s/%s" % (CASE, rel)],
                       capture_output=True, text=True, timeout=120)
    return r.stdout


def tee(rel, content):
    r = subprocess.run(WSL + ["tee", "%s/%s" % (CASE, rel)],
                       input=content, capture_output=True, text=True, timeout=120)
    return r.returncode


# ---- S-A preset (mirrors T-006 Run 1) ----
p = "system/fvSolution"
t = cat(p)
assert "nNonOrthogonalCorrectors 0;" in t, "ASSERT: nNonOrthogonalCorrectors 0 not found"
t = t.replace("nNonOrthogonalCorrectors 0;", "nNonOrthogonalCorrectors 2;")
old_relax = "relaxationFactors { equations { U 0.9; } }"
assert old_relax in t, "ASSERT: relaxation U 0.9 pattern not found"
t = t.replace(old_relax, "relaxationFactors { equations { U 0.7; } fields { p 0.3; } }")
tee(p, t)
print("fvSolution -> S-A (nNonOrth 2, U 0.7, fields{p 0.3})", flush=True)

p = "system/fvSchemes"
s = cat(p)
if "grad(U) cellLimited" not in s:
    m = re.search(r"default\s+Gauss linear;", s)
    assert m, "ASSERT: grad default pattern not found"
    s = s[:m.end()] + "\n    grad(U) cellLimited Gauss linear 1;" + s[m.end():]
    tee(p, s)
    print("fvSchemes -> grad(U) cellLimited", flush=True)
else:
    print("fvSchemes already has grad(U) cellLimited", flush=True)

p = "system/controlDict"
c = cat(p)
assert "endTime 2000;" in c, "ASSERT: endTime 2000 not found"
c = c.replace("endTime 2000;", "endTime 600;")
tee(p, c)
print("controlDict endTime 2000 -> 600", flush=True)

print("--- verify ---", flush=True)
print([l.strip() for l in cat("system/fvSolution").splitlines()
       if "nNonOrth" in l or "relaxation" in l], flush=True)
print([l.strip() for l in cat("system/fvSchemes").splitlines() if "grad" in l], flush=True)
print([l.strip() for l in cat("system/controlDict").splitlines() if "endTime" in l], flush=True)

# ---- run simpleFoam (direct, bypassing run_openfoam_case mesh gate;
#      Mesh OK is a recorded item per M1/M2 user ruling) ----
print("--- launching simpleFoam ---", flush=True)
r = subprocess.run(WSL + ["bash", "-c",
                          "cd %s && source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1 "
                          "&& simpleFoam > log.simpleFoam 2>&1; echo RC=$?" % CASE],
                   capture_output=True, text=True)
print(r.stdout[-500:], flush=True)
print("DONE", flush=True)
