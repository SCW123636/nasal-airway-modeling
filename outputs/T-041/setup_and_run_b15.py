import re
import subprocess
from pathlib import Path

WSL = ["wsl.exe", "-d", "Ubuntu-22.04", "--"]
CASE = "/home/lenovo2/patient_cfd/b15_maxh1"
B01 = Path("C:/ts_work/t041_b01/b01_h1p0")


def sh(args, t=60):
    return subprocess.run(WSL + args, capture_output=True, text=True, timeout=t)


def cat(rel):
    return sh(["cat", "%s/%s" % (CASE, rel)]).stdout


def tee(rel, content):
    r = subprocess.run(WSL + ["tee", "%s/%s" % (CASE, rel)], input=content,
                       capture_output=True, text=True, timeout=120)
    return r.returncode


# ---- 1. read b15 actual patch names from polyMesh/boundary ----
bd = cat("constant/polyMesh/boundary")
body = bd.split("// * * *", 1)[-1]
names = re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*$\s*\{", body, re.M)
if not names:
    names = re.findall(r"^\s{4}([A-Za-z_][A-Za-z0-9_]*)\s*$", body, re.M)
print("b15 patches:", names, flush=True)
assert "nostril_L" in names and "nostril_R" in names, "ASSERT: nostril patches missing"
outlet = "nasopharynx_outlet" if "nasopharynx_outlet" in names else None
assert outlet, "ASSERT: outlet patch missing"
walls = [n for n in names if n in ("wall",)]
assert walls, "ASSERT: wall patch missing"
print("outlet =", outlet, "walls =", walls, flush=True)

# ---- 2. build 0/U, 0/p with ONLY the patches that exist ----
# flow: 2.5e-4 m3/s total (15 L/min), split evenly between the two nostrils
Q_TOTAL = 2.5e-4
half = Q_TOTAL / 2.0

u_lines = []
p_lines = []
for n in names:
    if n in ("nostril_L", "nostril_R"):
        u_lines.append("    %s { type flowRateInletVelocity; volumetricFlowRate constant %.9g; }"
                       % (n, half))
        p_lines.append("    %s { type zeroGradient; }" % n)
    elif n == outlet:
        u_lines.append("    %s { type zeroGradient; }" % n)
        p_lines.append("    %s { type fixedValue; value uniform 0; }" % n)
    else:
        u_lines.append("    %s { type noSlip; }" % n)
        p_lines.append("    %s { type zeroGradient; }" % n)

U_TXT = """FoamFile
{{
    version     2.0;
    format      ascii;
    class       volVectorField;
    object      U;
}}

dimensions [0 1 -1 0 0 0 0];
internalField uniform (0 0 0);
boundaryField
{{
{}
}}
""".format("\n".join(u_lines))

P_TXT = """FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      p;
}}

dimensions [0 2 -2 0 0 0 0];
internalField uniform 0;
boundaryField
{{
{}
}}
""".format("\n".join(p_lines))

sh(["mkdir", "-p", "%s/0" % CASE])
tee("0/U", U_TXT)
tee("0/p", P_TXT)
print("wrote 0/U and 0/p", flush=True)

# ---- 3. copy solver-level properties verbatim from the b01 case ----
for rel in ("transportProperties", "turbulenceProperties"):
    src = B01 / "constant" / rel
    if src.is_file():
        tee("constant/%s" % rel, src.read_text(encoding="utf-8"))
        print("copied constant/%s" % rel, flush=True)
    else:
        print("WARN missing %s" % src, flush=True)

# ---- 4. run simpleFoam (direct; Mesh OK is a recorded item per M1/M2 ruling) ----
print("--- launching simpleFoam ---", flush=True)
r = sh(["bash", "-c",
        "cd %s && source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1 "
        "&& simpleFoam > log.simpleFoam 2>&1; echo RC=$?" % CASE], 300000)
print(r.stdout[-800:], flush=True)
print("DONE", flush=True)
