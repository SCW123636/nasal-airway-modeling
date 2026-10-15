#!/bin/bash
# T-058 per-case chain: production auto_placed.vtp (already converted to STL on
# the Windows side) -> netgen volume mesh -> boundary repair -> gmshToFoam ->
# checkMesh -> wall patch type -> S-A laminar solve (600 steps) -> wallShearStress
# post-process -> ASCII VTK.  Runs INSIDE WSL (Ubuntu-22.04), OpenFOAM v1912.
# All variables live inside this file (never cross the wsl.exe boundary).
#
# Usage: bash chain_case.sh <case>     e.g. bash chain_case.sh b15
#
# Inputs expected on the Windows side (staging, made by vtp_to_stl_t047.py):
#   /mnt/c/ts_work/t058_chain/<case>/placed.stl
#   /mnt/c/ts_work/t058_chain/<case>/export.json
# Outputs: /home/lenovo2/t058_chain/<case>/  (mesh, foam case, logs, wall_600.vtp)
set -e
CASE="$1"
STAGE=/home/lenovo2/t058_chain/$CASE
WIN=/mnt/c/ts_work/t058_chain/$CASE
SCRIPTS=/home/lenovo2/patient_cfd/t054_b15_oroext
VENV=/home/lenovo2/netgen_venv/bin/python
SRC=/home/lenovo2/patient_cfd/b15_maxh1
CASE_DIR=$STAGE/foam_maxh1

source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1
mkdir -p "$STAGE"
cp "$WIN/placed.stl" "$WIN/export.json" "$STAGE/"

echo "== step 1: netgen volume mesh (maxh 1.0, T-054 preset) =="
$VENV "$SCRIPTS/netgen_patient_mesh_t047.py" "$STAGE/placed.stl" "$STAGE/export.json" \
      "$STAGE/maxh1.msh" --maxh 1.0 2>&1 | tail -4

echo "== step 2: repair boundary tetrahedra =="
$VENV "$SCRIPTS/repair_boundary_tetrahedra.py" "$STAGE/maxh1.msh" \
      "$STAGE/maxh1_repaired.msh" 2>&1 | tail -4

echo "== step 3: scaffold + gmshToFoam =="
mkdir -p "$CASE_DIR/constant" "$CASE_DIR/system"
cp "$SRC/system/controlDict" "$SRC/system/fvSchemes" "$SRC/system/fvSolution" "$CASE_DIR/system/"
cp "$SRC/constant/transportProperties" "$SRC/constant/turbulenceProperties" "$CASE_DIR/constant/"
sed -i 's/nasopharynx_outlet/oropharynx_truncation_outlet/g' "$CASE_DIR/system/controlDict"
cp "$STAGE/maxh1_repaired.msh" "$CASE_DIR/case.msh"
(cd "$CASE_DIR" && gmshToFoam case.msh > gmshToFoam.log 2>&1)
(cd "$CASE_DIR" && checkMesh -allGeometry -allTopology > checkMesh.log 2>&1 || true)
grep -E "cells:|Mesh non-orthogonality|Max aspect ratio|Failed|OK\." "$CASE_DIR/checkMesh.log" | head -10

echo "== step 4: wall patch type -> wall (wallShearStress silently zeroes on type patch) =="
python3 "$STAGE/../patch_wall_type.py" --case "$CASE_DIR" --patch wall || \
  { echo "PATCH_WALL_TYPE FAILED"; exit 2; }

echo "== step 5: 0/U + 0/p (S-A laminar, 125 mL/s per nostril, outlet p=0) =="
mkdir -p "$CASE_DIR/0"
cat > "$CASE_DIR/0/U" <<'EOF'
FoamFile
{
 version 2.0;
 format ascii;
 class volVectorField;
 object U;
}
dimensions [0 1 -1 0 0 0 0];
internalField uniform (0 0 0);
boundaryField
{
    nostril_L { type flowRateInletVelocity; volumetricFlowRate constant 1.25e-4; }
    nostril_R { type flowRateInletVelocity; volumetricFlowRate constant 1.25e-4; }
    oropharynx_truncation_outlet { type zeroGradient; }
    wall { type noSlip; }
}
EOF
cat > "$CASE_DIR/0/p" <<'EOF'
FoamFile
{
 version 2.0;
 format ascii;
 class volScalarField;
 object p;
}
dimensions [0 2 -2 0 0 0 0];
internalField uniform 0;
boundaryField
{
    nostril_L { type zeroGradient; }
    nostril_R { type zeroGradient; }
    oropharynx_truncation_outlet { type fixedValue; value uniform 0; }
    wall { type zeroGradient; }
}
EOF

echo "== step 6: S-A preset + patch-name sanity checks =="
grep -E "nNonOrthogonalCorrectors|U 0.7|p 0.3" "$CASE_DIR/system/fvSolution"
grep "grad(U) cellLimited" "$CASE_DIR/system/fvSchemes"
grep -E "^endTime" "$CASE_DIR/system/controlDict"
grep -E "^\s+(nostril_L|nostril_R|oropharynx_truncation_outlet|wall)\b" \
     "$CASE_DIR/constant/polyMesh/boundary" | head -6

echo "== step 7: simpleFoam (600 steps) =="
cd "$CASE_DIR"
simpleFoam > log.simpleFoam 2>&1
echo "simpleFoam exit=$?"
tail -2 log.simpleFoam
grep -E "^End" log.simpleFoam || echo "NO-END-MARKER"

echo "== step 8: wallShearStress post-process (latest time) =="
simpleFoam -postProcess -func wallShearStress -latestTime > log.wss 2>&1
echo "wss exit=$?"
ls -la 600/wallShearStress 2>/dev/null || { echo "NO wallShearStress field"; exit 3; }

echo "== step 9: foamToVTK -ascii (shared library reads ASCII only) =="
foamToVTK -ascii -time 600 > log.foamToVTK 2>&1
VTKDIR=$(ls -d VTK/foam_maxh1_* | tail -1)
echo "VTK dir: $VTKDIR"
ls "$VTKDIR/boundary/" | head -6
cp "$VTKDIR/boundary/wall.vtp" "$STAGE/wall_600.vtp"
echo "CHAIN-DONE $CASE"
