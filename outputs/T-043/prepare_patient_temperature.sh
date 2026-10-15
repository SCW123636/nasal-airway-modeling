#!/bin/bash
# T-043 patient temperature field: passive-scalar transport on the T-054 b15
# extended-domain converged laminar flow field (read-only source).
# Also fixes the T solver settings on the channel case (previous run hit maxIter).
# Runs INSIDE WSL. Literal paths only.
set -e

echo "== fix channel case T solver (tolerance reachable) =="
cd /home/lenovo2/t043_v2_diffusion
python3 - <<'PYEOF'
import re
p = "/home/lenovo2/t043_v2_diffusion/system/fvSolution"
s = open(p).read()
s = s.replace(
    "T { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-14; relTol 0; }",
    "T { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-12; relTol 0; maxIter 5000; }")
open(p, "w").write(s)
print("patched:", [l for l in s.splitlines() if l.strip().startswith("T {")])
PYEOF

echo "== prepare patient case =="
SRC=/home/lenovo2/patient_cfd/t054_b15_oroext/foam_maxh1
DST=/home/lenovo2/t043_b15_temp
rm -rf "$DST"
mkdir -p "$DST"
cp -r "$SRC/constant" "$DST/constant"
cp -r "$SRC/system" "$DST/system"
mkdir -p "$DST/0"
cp "$SRC/600/U" "$SRC/600/p" "$SRC/600/phi" "$DST/0/"

cat > "$DST/0/T" <<'EOF'
FoamFile
{
    version     2.0;
    format      ascii;
    class       volScalarField;
    location    "0";
    object      T;
}
dimensions      [0 0 0 1 0 0 0];
internalField   uniform 293.15;
boundaryField
{
    nostril_L                     { type fixedValue; value uniform 293.15; }
    nostril_R                     { type fixedValue; value uniform 293.15; }
    wall                          { type fixedValue; value uniform 306.15; }
    oropharynx_truncation_outlet  { type zeroGradient; }
}
EOF

cat > "$DST/constant/transportProperties" <<'EOF'
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    location    "constant";
    object      transportProperties;
}
transportModel  Newtonian;
nu              1.5e-05;
DT              [0 2 -1 0 0 0 0] 2.5e-05;
EOF

# fvSchemes: add T convection (laplacian already defaults to Gauss linear corrected)
python3 - <<'PYEOF'
p = "/home/lenovo2/t043_b15_temp/system/fvSchemes"
s = open(p).read()
if "div(phi,T)" not in s:
    s = s.replace("div(phi,U)", "div(phi,U)\n    div(phi,T)      bounded Gauss limitedLinear 1;", 1)
open(p, "w").write(s)
print("div(phi,T) present:", "div(phi,T)" in open(p).read())
PYEOF

# fvSolution: add T solver
python3 - <<'PYEOF'
p = "/home/lenovo2/t043_b15_temp/system/fvSolution"
s = open(p).read()
if "\n    T {" not in s:
    s = s.replace("omega {", "T { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-12; relTol 0; maxIter 5000; }\n    omega {", 1)
open(p, "w").write(s)
print("T solver present:", "T { solver smoothSolver" in open(p).read())
PYEOF

# controlDict: scalar transport, single steady solve, surface probes
python3 - <<'PYEOF'
p = "/home/lenovo2/t043_b15_temp/system/controlDict"
s = open(p).read()
s = s.replace("application     simpleFoam;", "application     scalarTransportFoam;")
s = s.replace("startFrom       latestTime;", "startFrom       startTime;")
s = s.replace("endTime         600;", "endTime         1;")
s = s.replace("writeInterval   200;", "writeInterval   1;")
if "functions" not in s:
    s += """
functions
{
    Tnostril
    {
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        writeControl    writeTime;
        writeFields     no;
        log             yes;
        regionType      patch;
        name            nostril_L;
        operation       areaAverage;
        fields          (T);
    }
    Toutlet
    {
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        writeControl    writeTime;
        writeFields     no;
        log             yes;
        regionType      patch;
        name            oropharynx_truncation_outlet;
        operation       areaAverage;
        fields          (T);
    }
    Twall
    {
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        writeControl    writeTime;
        writeFields     no;
        log             yes;
        regionType      patch;
        name            wall;
        operation       areaAverage;
        fields          (T);
    }
}
"""
open(p, "w").write(s)
print("controlDict patched")
PYEOF

echo "== sanity: patch names vs T boundary =="
grep -E "^\s+(nostril_L|nostril_R|oropharynx_truncation_outlet|wall)\b" "$DST/constant/polyMesh/boundary" | head -8
echo "== T BC =="
grep -A 1 "boundaryField" "$DST/0/T" | head -12
echo "PREPARED-PATIENT-CASE"
