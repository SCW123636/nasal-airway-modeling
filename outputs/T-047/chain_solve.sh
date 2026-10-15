#!/bin/bash
# T-047 chain: repair .msh -> gmshToFoam -> checkMesh -> prepare S-A case.
# Runs INSIDE WSL (Ubuntu-22.04), OpenFOAM v1912. No inline variables cross the
# wsl.exe boundary (this file is copied then executed, avoiding the eaten-$ trap).
set -e
WORK=/home/lenovo2/patient_cfd/t047_b01_oroext
VENV=/home/lenovo2/netgen_venv/bin/python
SRC=/home/lenovo2/patient_cfd/b15_maxh1
CASE=$WORK/foam_maxh1
RAW=$WORK/b01_oroext_maxh1.msh
REP=$WORK/b01_oroext_maxh1_repaired.msh

source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1

echo "== step 1: repair boundary tetrahedra =="
if [ ! -f "$REP" ]; then
  $VENV $WORK/repair_boundary_tetrahedra.py "$RAW" "$REP" | tee $WORK/repair.log
else
  echo "repaired msh exists, skip"
fi

echo "== step 2: case scaffold + gmshToFoam (raw AND repaired) =="
for MESH in raw repaired; do
  if [ "$MESH" = raw ]; then MSH=$RAW; CDIR=$WORK/foam_raw_check; else MSH=$REP; CDIR=$CASE; fi
  mkdir -p $CDIR/constant $CDIR/system
  cp $SRC/system/controlDict $SRC/system/fvSchemes $SRC/system/fvSolution $CDIR/system/
  cp $SRC/constant/transportProperties $SRC/constant/turbulenceProperties $CDIR/constant/
  sed -i 's/nasopharynx_outlet/oropharynx_truncation_outlet/g' $CDIR/system/controlDict
  cp $MSH $CDIR/case.msh
  (cd $CDIR && gmshToFoam case.msh > gmshToFoam.log 2>&1)
  (cd $CDIR && checkMesh -allGeometry -allTopology > checkMesh.log 2>&1 || true)
  echo "-- $MESH checkMesh summary --"
  grep -E "cells:|faces:|points:|Mesh non-orthogonality|Max aspect ratio|Failed|OK\." $CDIR/checkMesh.log | head -12
  grep -c "cell determinant" $CDIR/checkMesh.log || true
done

echo "== step 3: 0/U 0/p on the repaired case =="
mkdir -p $CASE/0
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
    oropharynx_truncation_outlet { type zeroGradient; }
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
    oropharynx_truncation_outlet { type fixedValue; value uniform 0; }
    wall { type zeroGradient; }
}
EOF

echo "== step 4: verify patch names vs boundary file =="
grep -E "^\s+(nostril_L|nostril_R|oropharynx_truncation_outlet|wall|defaultFaces)\b" $CASE/constant/polyMesh/boundary || sed -n '/FoamFile/,$p' $CASE/constant/polyMesh/boundary | grep -B1 "type patch" | head -20

echo "== step 5: S-A preset state check =="
grep -E "nNonOrthogonalCorrectors|U 0.7|p 0.3" $CASE/system/fvSolution
grep "grad(U) cellLimited" $CASE/system/fvSchemes
grep -E "^endTime" $CASE/system/controlDict

echo "PREPARED $CASE"
