#!/bin/bash
# T-043 synthetic verification: scalarTransportFoam on plane Poiseuille channel.
# V1 = pure-convection limit (DT=0): outlet T must equal inlet T (293.15 K).
#      -> validates convection term + BC wiring independent of diffusion.
# V2 = with diffusion (DT=2.5e-5): outlet T must rise toward wall T (306.15 K).
# Runs INSIDE WSL (copied then executed; no shell vars cross the wsl.exe boundary).
set -e
SRC=/mnt/d/项目/鼻腔建模/work/07_cfd_pipeline/solver_reference/results/poiseuille_v1912_verified/medium

for V in v1_pureconv v2_diffusion; do
  DST=/home/lenovo2/t043_$V
  rm -rf "$DST"
  mkdir -p "$DST"
  cp -r "$SRC/constant" "$DST/constant"
  cp -r "$SRC/system" "$DST/system"
  mkdir -p "$DST/0"
  # converged steady flow field as the 0/ state (steadyState ddt -> solved once)
  cp "$SRC/155/U" "$SRC/155/p" "$SRC/155/phi" "$DST/0/"

  if [ "$V" = "v1_pureconv" ]; then DTVAL=0; else DTVAL=2.5e-05; fi

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
    inlet        { type fixedValue; value uniform 293.15; }
    outlet       { type zeroGradient; }
    walls        { type fixedValue; value uniform 306.15; }
    frontAndBack { type empty; }
}
EOF

  cat > "$DST/constant/transportProperties" <<EOF
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    location    "constant";
    object      transportProperties;
}
transportModel  Newtonian;
nu              1.508333333333333e-05;
DT              [0 2 -1 0 0 0 0] $DTVAL;
EOF

  cat > "$DST/system/fvSchemes" <<'EOF'
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    location    "system";
    object      fvSchemes;
}
ddtSchemes      { default         steadyState; }
gradSchemes     { default         Gauss linear; }
divSchemes
{
    default         none;
    div(phi,U)      bounded Gauss linearUpwind grad(U);
    div(phi,T)      bounded Gauss limitedLinear 1;
}
laplacianSchemes
{
    default         Gauss linear corrected;
    laplacian(DT,T) Gauss linear corrected;
}
interpolationSchemes { default linear; }
snGradSchemes   { default corrected; }
EOF

  cat > "$DST/system/fvSolution" <<'EOF'
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    location    "system";
    object      fvSolution;
}
solvers
{
    p { solver GAMG; tolerance 1e-12; relTol 0.01; smoother GaussSeidel; }
    U { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-12; relTol 0.01; }
    T { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-14; relTol 0; }
}
SIMPLE
{
    nNonOrthogonalCorrectors 0;
    consistent yes;
    residualControl { p 1e-10; U 1e-8; }
}
EOF

  cat > "$DST/system/controlDict" <<'EOF'
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    location    "system";
    object      controlDict;
}
application     scalarTransportFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         1;
deltaT          1;
writeControl    timeStep;
writeInterval   1;
purgeWrite      0;
writeFormat     ascii;
writePrecision  10;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;
functions
{
    Tin
    {
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        writeControl    writeTime;
        writeFields     no;
        log             yes;
        regionType      patch;
        name            inlet;
        operation       areaAverage;
        fields          (T);
    }
    Tout
    {
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        writeControl    writeTime;
        writeFields     no;
        log             yes;
        regionType      patch;
        name            outlet;
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
        name            walls;
        operation       areaAverage;
        fields          (T);
    }
}
EOF

  echo "PREPARED $V (DT=$DTVAL)"
done
