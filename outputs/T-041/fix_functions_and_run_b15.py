import subprocess

WSL = ["wsl.exe", "-d", "Ubuntu-22.04", "--"]
CASE = "/home/lenovo2/patient_cfd/b15_maxh1"


def sh(args, t=60):
    return subprocess.run(WSL + args, capture_output=True, text=True, timeout=t)


def cat(rel):
    return sh(["cat", "%s/%s" % (CASE, rel)]).stdout


def tee(rel, content):
    r = subprocess.run(WSL + ["tee", "%s/%s" % (CASE, rel)], input=content,
                       capture_output=True, text=True, timeout=120)
    return r.returncode


def monitor(name, patch, op, field):
    return """{name}
{{
 type surfaceFieldValue;
 libs ("libfieldFunctionObjects.so");
 regionType patch;
 name {patch};
 operation {op};
 fields ({field});
 writeFields false;
 log false;
 writeControl timeStep;
 writeInterval 1;
}}""".format(name=name, patch=patch, op=op, field=field)


OUT = "nasopharynx_outlet"
blocks = [
    monitor("flowInL", "nostril_L", "sum", "phi"),
    monitor("flowInR", "nostril_R", "sum", "phi"),
    monitor("flowOut", OUT, "sum", "phi"),
    monitor("pressureInL", "nostril_L", "areaAverage", "p"),
    monitor("pressureInR", "nostril_R", "areaAverage", "p"),
    monitor("pressureOut", OUT, "areaAverage", "p"),
]
functions = "functions\n{\n" + "\n".join(blocks) + "\n}\n"

cd = cat("system/controlDict")
i = cd.find("functions")
assert i >= 0, "ASSERT: functions block not found in controlDict"
fixed = cd[:i] + functions
tee("system/controlDict", fixed)
print("controlDict functions rewritten for b15 patches", flush=True)

verify = cat("system/controlDict")
import re
print("patch names now used:",
      sorted(set(re.findall(r"^\s{1}name\s+(\S+);", verify, re.M))), flush=True)
assert "inlet" not in verify, "ASSERT: stale 'inlet' remains"
assert "outlet" not in verify.replace(OUT, ""), "ASSERT: stale bare 'outlet' remains"

print("--- launching simpleFoam ---", flush=True)
r = sh(["bash", "-c",
        "cd %s && source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1 "
        "&& simpleFoam > log.simpleFoam 2>&1; echo RC=$?" % CASE], 300000)
print(r.stdout[-800:], flush=True)
print("DONE", flush=True)
