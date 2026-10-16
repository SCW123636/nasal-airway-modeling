#!/bin/bash
# T-011 A.1 (snappyHexMesh route) - field setup + steady laminar solve.
# Numeric setup is byte-identical to b15 (S-A laminar preset from b15_maxh1):
#   nNonOrthogonalCorrectors 2, U 0.7, p 0.3, grad(U) cellLimited, endTime 600,
#   125 mL/s per nostril (= 1.25e-4 m^3/s), outlet p = 0.
# The ONLY deliberate difference from b15 is the mesher (snappy vs netgen).
CASE=/home/lenovo2/t011_p0/snappy
STAGE=/home/lenovo2/t011_p0
source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1
cd "$CASE" || { echo "NO CASE DIR"; exit 1; }

banner() { echo; echo "== $* =="; }

banner "step 1: 0/U + 0/p"
mkdir -p 0
cat > 0/U <<'EOF'
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
cat > 0/p <<'EOF'
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

# Resumable: controlDict uses startFrom latestTime, so an interrupted run picks up
# from the last written time instead of restarting. The first attempt was killed
# by a cross-session `pkill -x simpleFoam` at Time=343 (another session's T-062
# probe cleanup matches this process name). FRESH=1 forces a restart from 0.
# writeInterval is tightened 200 -> 50 so such a kill costs at most 50 iterations.
sed -i 's/writeInterval *200;/writeInterval 50;/' system/controlDict
if [ "${FRESH:-0}" = "1" ]; then
  for d in $(ls -d [0-9]* 2>/dev/null); do [ "$d" != "0" ] && rm -rf "$d"; done
fi
echo "existing time dirs:"; ls -d [0-9]* 2>/dev/null | tr '\n' ' '; echo

banner "step 2: preset + boundary sanity"
grep -E "nNonOrthogonalCorrectors|U +0.7|p +0.3" system/fvSolution
grep "grad(U) cellLimited" system/fvSchemes
grep -E "^endTime" system/controlDict
grep -c "laminar" constant/turbulenceProperties
echo "--- patches in mesh ---"
grep -E "^\s{4}(nostril_L|nostril_R|oropharynx_truncation_outlet|wall)\b" constant/polyMesh/boundary

banner "step 3: simpleFoam (600 iterations)"
/usr/bin/time -v simpleFoam > log.simpleFoam 2>&1
RC=$?
echo "simpleFoam exit=$RC"
grep -E "Maximum resident set size|Elapsed \(wall" log.simpleFoam
tail -3 log.simpleFoam
grep -E "^End" log.simpleFoam || echo "NO-END-MARKER"
if [ $RC -ne 0 ]; then echo "SOLVE FAILED rc=$RC"; exit 1; fi

banner "step 4: wallShearStress (latest time)"
simpleFoam -postProcess -func wallShearStress -latestTime > log.wss 2>&1
echo "wss exit=$?"
ls -la 600/wallShearStress 2>/dev/null || echo "NO wallShearStress field"

banner "step 5: foamToVTK -ascii"
foamToVTK -ascii -time 600 > log.foamToVTK 2>&1
VTKDIR=$(ls -d VTK/snappy_*/ 2>/dev/null | tail -1)
echo "VTK dir: $VTKDIR"
ls "$VTKDIR/boundary/" 2>/dev/null | head -8
mkdir -p "$STAGE/out_snappy"
cp "$VTKDIR/boundary/"*.vtp "$STAGE/out_snappy/" 2>/dev/null || echo "no boundary vtp"
cp "$VTKDIR/internal.vtu" "$STAGE/out_snappy/internal_600.vtu" 2>/dev/null || echo "no internal.vtu"
echo "SNAPPY-SOLVE-DONE"
