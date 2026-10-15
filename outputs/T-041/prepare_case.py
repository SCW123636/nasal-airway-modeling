"""Prepare an existing gmshToFoam-converted patient case for S-A solving.

Many converted cases under /home/lenovo2/patient_cfd have constant/polyMesh +
system but NO 0/ fields (they stopped after gmshToFoam + checkMesh). This fills
in what is missing, using the b01 reference case (built by surface_to_case) as
the source for solver-level properties, and rewrites every functionObject /
preset to the case's ACTUAL patch names.

S-A preset mirrors T-006 Run 1: nNonOrth 2, U 0.7 + fields{p 0.3}, grad(U)
cellLimited.  Every edit is asserted so a stale pattern cannot silently no-op.
"""
import argparse
import re
import subprocess
from pathlib import Path

WSL = ["wsl.exe", "-d", "Ubuntu-22.04", "--"]
B01 = Path("C:/ts_work/t041_b01/b01_h1p0")
Q_TOTAL = 2.5e-4          # m^3/s == 15 L/min
END_TIME = 600


def sh(args, t=120):
    return subprocess.run(WSL + args, capture_output=True, text=True, timeout=t)


def make(case):
    def cat(rel):
        return sh(["cat", "%s/%s" % (case, rel)]).stdout

    def tee(rel, content):
        return subprocess.run(WSL + ["tee", "%s/%s" % (case, rel)], input=content,
                              capture_output=True, text=True, timeout=120).returncode
    return cat, tee


def patches(cat):
    bd = cat("constant/polyMesh/boundary")
    body = bd.split("// * * *", 1)[-1]
    names = re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*$\s*\{", body, re.M)
    if not names:
        names = re.findall(r"^\s{4}([A-Za-z_][A-Za-z0-9_]*)\s*$", body, re.M)
    return names


def monitor(name, patch, op, field):
    return """{n}
{{
 type surfaceFieldValue;
 libs ("libfieldFunctionObjects.so");
 regionType patch;
 name {p};
 operation {o};
 fields ({f});
 writeFields false;
 log false;
 writeControl timeStep;
 writeInterval 1;
}}""".format(n=name, p=patch, o=op, f=field)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--maxh-note", default="")
    args = ap.parse_args()
    case = args.case
    cat, tee = make(case)

    names = patches(cat)
    print("case:", case, flush=True)
    print("patches:", names, flush=True)
    assert "nostril_L" in names and "nostril_R" in names, "ASSERT: nostrils missing"
    outlet = next((n for n in names if "outlet" in n.lower() or "naso" in n.lower()), None)
    assert outlet, "ASSERT: outlet patch missing"

    # ---- 0/U, 0/p ----
    half = Q_TOTAL / 2.0
    u, p = [], []
    for n in names:
        if n in ("nostril_L", "nostril_R"):
            u.append("    %s { type flowRateInletVelocity; volumetricFlowRate constant %.9g; }" % (n, half))
            p.append("    %s { type zeroGradient; }" % n)
        elif n == outlet:
            u.append("    %s { type zeroGradient; }" % n)
            p.append("    %s { type fixedValue; value uniform 0; }" % n)
        elif n.lower() == "wall":
            u.append("    %s { type noSlip; }" % n)
            p.append("    %s { type zeroGradient; }" % n)
        else:
            u.append("    %s { type zeroGradient; }" % n)
            p.append("    %s { type zeroGradient; }" % n)

    U = ('FoamFile\n{\n version 2.0;\n format ascii;\n class volVectorField;\n object U;\n}\n\n'
         'dimensions [0 1 -1 0 0 0 0];\ninternalField uniform (0 0 0);\nboundaryField\n{\n'
         + "\n".join(u) + '\n}\n')
    P = ('FoamFile\n{\n version 2.0;\n format ascii;\n class volScalarField;\n object p;\n}\n\n'
         'dimensions [0 2 -2 0 0 0 0];\ninternalField uniform 0;\nboundaryField\n{\n'
         + "\n".join(p) + '\n}\n')
    sh(["mkdir", "-p", "%s/0" % case])
    tee("0/U", U)
    tee("0/p", P)
    print("wrote 0/U, 0/p", flush=True)

    for rel in ("transportProperties", "turbulenceProperties"):
        src = B01 / "constant" / rel
        if src.is_file():
            tee("constant/%s" % rel, src.read_text(encoding="utf-8"))
            print("copied constant/%s" % rel, flush=True)

    # ---- functionObjects on real patch names ----
    blocks = [monitor("flowInL", "nostril_L", "sum", "phi"),
              monitor("flowInR", "nostril_R", "sum", "phi"),
              monitor("flowOut", outlet, "sum", "phi"),
              monitor("pressureInL", "nostril_L", "areaAverage", "p"),
              monitor("pressureInR", "nostril_R", "areaAverage", "p"),
              monitor("pressureOut", outlet, "areaAverage", "p")]
    cd = cat("system/controlDict")
    i = cd.find("functions")
    assert i >= 0, "ASSERT: functions block missing"
    cd = cd[:i] + "functions\n{\n" + "\n".join(blocks) + "\n}\n"
    assert re.search(r"^\s*endTime\s+\d+;", cd, re.M), "ASSERT: endTime missing"
    cd = re.sub(r"^\s*endTime\s+\d+;", "endTime %d;" % END_TIME, cd, count=1, flags=re.M)
    tee("system/controlDict", cd)
    print("controlDict: functions -> real patches, endTime -> %d" % END_TIME, flush=True)

    # ---- S-A preset ----
    t = cat("system/fvSolution")
    assert "nNonOrthogonalCorrectors 0;" in t, "ASSERT: nNonOrth 0 missing"
    t = t.replace("nNonOrthogonalCorrectors 0;", "nNonOrthogonalCorrectors 2;")
    old = "relaxationFactors { equations { U 0.9; } }"
    assert old in t, "ASSERT: relax U 0.9 missing"
    t = t.replace(old, "relaxationFactors { equations { U 0.7; } fields { p 0.3; } }")
    tee("system/fvSolution", t)

    s = cat("system/fvSchemes")
    if "grad(U) cellLimited" not in s:
        m = re.search(r"default\s+Gauss linear;", s)
        assert m, "ASSERT: grad default missing"
        s = s[:m.end()] + "\n    grad(U) cellLimited Gauss linear 1;" + s[m.end():]
        tee("system/fvSchemes", s)
    print("S-A preset applied", flush=True)

    print("--- verify ---", flush=True)
    v = cat("system/fvSolution")
    print([l.strip() for l in v.splitlines() if "nNonOrth" in l or "relaxation" in l], flush=True)
    print([l.strip() for l in cat("system/controlDict").splitlines() if "endTime" in l], flush=True)
    print("PREPARED", flush=True)

    if args.run:
        print("--- launching simpleFoam ---", flush=True)
        r = sh(["bash", "-c", "cd %s && source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1 "
                             "&& simpleFoam > log.simpleFoam 2>&1; echo RC=$?" % case], 300000)
        print(r.stdout[-600:], flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
