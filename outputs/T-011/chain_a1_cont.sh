#!/bin/bash
# T-011 Phase A.1 continuation: repair -> gmshToFoam -> checkMesh -> wall patch
#   type -> 0/U,0/p -> simpleFoam 600 -> wallShearStress -> foamToVTK -ascii.
# Starts from an ALREADY-BUILT netgen mesh ($STAGE/MESH), so the expensive
# netgen step can be run and validated on its own.
#
# Same rules as chain_a1.sh: no `set -u` (it aborts on the OpenFOAM bashrc),
# explicit RC capture after every stage (no pipeline masking).
CASE=p0
STAGE=/home/lenovo2/t011_p0
SCRIPTS=/home/lenovo2/patient_cfd/t054_b15_oroext
VENV=/home/lenovo2/netgen_venv/bin/python
SRC=/home/lenovo2/patient_cfd/b15_maxh1
WALLTOOL=/home/lenovo2/t058_chain_anat/patch_wall_type.py
MESH=${MESH:-$STAGE/maxh1_cln.msh}
CASE_DIR=$STAGE/foam_A1

source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1
mkdir -p "$STAGE" "$STAGE/out"
rm -rf "$CASE_DIR"
[ -f "$MESH" ] || { echo "MESH MISSING: $MESH"; exit 1; }

banner() { echo; echo "== $* =="; }

banner "step 2: repair boundary tetrahedra ($MESH)"
$VENV "$SCRIPTS/repair_boundary_tetrahedra.py" "$MESH" \
      "$STAGE/A1_repaired.msh" > "$STAGE/repair_A1.log" 2>&1
RC=$?
tail -6 "$STAGE/repair_A1.log"
if [ $RC -ne 0 ]; then echo "REPAIR FAILED rc=$RC"; exit 1; fi

banner "step 3: scaffold + gmshToFoam + checkMesh"
mkdir -p "$CASE_DIR/constant" "$CASE_DIR/system"
cp "$SRC/system/controlDict" "$SRC/system/fvSchemes" "$SRC/system/fvSolution" "$CASE_DIR/system/"
cp "$SRC/constant/transportProperties" "$SRC/constant/turbulenceProperties" "$CASE_DIR/constant/"
sed -i 's/nasopharynx_outlet/oropharynx_truncation_outlet/g' "$CASE_DIR/system/controlDict"
cp "$STAGE/A1_repaired.msh" "$CASE_DIR/case.msh"
( cd "$CASE_DIR" && gmshToFoam case.msh > gmshToFoam.log 2>&1 ); RC=$?
if [ $RC -ne 0 ]; then echo "gmshToFoam FAILED rc=$RC"; tail -20 "$CASE_DIR/gmshToFoam.log"; exit 1; fi
( cd "$CASE_DIR" && checkMesh -allGeometry -allTopology > checkMesh.log 2>&1 )
grep -E "cells:|Mesh non-orthogonality|Max aspect ratio|Failed|OK\." "$CASE_DIR/checkMesh.log" | head -12

banner "step 4: wall patch type -> wall"
python3 "$WALLTOOL" --case "$CASE_DIR" --patch wall || { echo "PATCH_WALL_TYPE FAILED"; exit 2; }

banner "step 5: 0/U + 0/p (S-A laminar, 125 mL/s per nostril, outlet p=0)"
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

banner "step 6: preset + patch-name sanity checks"
grep -E "nNonOrthogonalCorrectors|U 0.7|p 0.3" "$CASE_DIR/system/fvSolution"
grep "grad(U) cellLimited" "$CASE_DIR/system/fvSchemes"
grep -E "^endTime" "$CASE_DIR/system/controlDict"
grep -E "^\s+(nostril_L|nostril_R|oropharynx_truncation_outlet|wall)\b" \
     "$CASE_DIR/constant/polyMesh/boundary" | head -6

banner "step 7: simpleFoam (600 steps)"
cd "$CASE_DIR"
simpleFoam > log.simpleFoam 2>&1
SFRC=$?
echo "simpleFoam exit=$SFRC"
tail -3 log.simpleFoam
grep -E "^End" log.simpleFoam || echo "NO-END-MARKER"

banner "step 8: wallShearStress post-process (latest time)"
simpleFoam -postProcess -func wallShearStress -latestTime > log.wss 2>&1
echo "wss exit=$?"
ls -la 600/wallShearStress 2>/dev/null || echo "NO wallShearStress field"

banner "step 9: foamToVTK -ascii"
foamToVTK -ascii -time 600 > log.foamToVTK 2>&1
VTKDIR=$(ls -d VTK/foam_A1_*/ 2>/dev/null | tail -1)
echo "VTK dir: $VTKDIR"
ls "$VTKDIR/boundary/" 2>/dev/null | head -8
cp "$VTKDIR/boundary/"*.vtp "$STAGE/out/" 2>/dev/null || echo "no boundary vtp"
cp "$VTKDIR/internal.vtu" "$STAGE/out/internal_A1_600.vtu" 2>/dev/null || echo "no internal.vtu"
echo "CHAIN-DONE $CASE"
