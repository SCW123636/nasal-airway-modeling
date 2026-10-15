#!/bin/bash
# T-047 A/B arm: b01 SHORT domain (production 3-label, nasopharynx outlet).
# Same chain as the extended arm, identical netgen version + params; the ONLY
# difference is the domain (nasopharynx-outlet vs oropharynx-truncation).
set -e
WORK=/home/lenovo2/patient_cfd/t047_b01_short
VENV=/home/lenovo2/netgen_venv/bin/python
SRC=/home/lenovo2/patient_cfd/b15_maxh1
CASE=$WORK/foam_maxh1
RAW=$WORK/b01_short_maxh1.msh
REP=$WORK/b01_short_maxh1_repaired.msh

source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1
cd $WORK

echo "== step 0: mesh if missing =="
if [ ! -f "$RAW" ]; then
  $VENV $WORK/netgen_patient_mesh.py b01_short_placed.stl b01_short_placed.export.json b01_short_maxh1.msh --maxh 1.0 --dump-arrays b01_short_maxh1.arrays.npz | tee $WORK/mesh_run.log
fi

echo "== step 1: repair =="
if [ ! -f "$REP" ]; then
  $VENV $WORK/repair_boundary_tetrahedra.py "$RAW" "$REP" | tee $WORK/repair.log
fi

echo "== step 2: case + gmshToFoam + checkMesh =="
mkdir -p $CASE/constant $CASE/system $CASE/0
cp $SRC/system/controlDict $SRC/system/fvSchemes $SRC/system/fvSolution $CASE/system/
cp $SRC/constant/transportProperties $SRC/constant/turbulenceProperties $CASE/constant/
cp $REP $CASE/case.msh
(cd $CASE && gmshToFoam case.msh > gmshToFoam.log 2>&1)
(cd $CASE && checkMesh -allGeometry -allTopology > checkMesh.log 2>&1 || true)
grep -E "cells:|Mesh non-orthogonality|Failed|determinant" $CASE/checkMesh.log | head -6

echo "== step 3: 0/U 0/p (production patch names) =="
cat > $CASE/0/U <<'EOF'
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
    nasopharynx_outlet { type zeroGradient; }
    wall { type noSlip; }
}
EOF
cat > $CASE/0/p <<'EOF'
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
    nasopharynx_outlet { type fixedValue; value uniform 0; }
    wall { type zeroGradient; }
}
EOF

echo "== step 4: verify patches =="
grep -E "^\s+(nostril_L|nostril_R|nasopharynx_outlet|wall|defaultFaces)\b" $CASE/constant/polyMesh/boundary
echo "PREPARED $CASE"
