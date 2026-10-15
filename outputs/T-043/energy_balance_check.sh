#!/bin/bash
# T-043 verification step: energy balance on the plane-channel case.
#   Q_abs  = rho * Q * cp * (T_out - T_in)          [W], Q from sum(phi) on inlet
#   Q_wall = area-integral of wallHeatFlux on walls  [W]
#   pass if |Q_abs - Q_wall| / Q_abs <= 1%
# Runs INSIDE WSL. Literal paths only (no shell vars crossing the wsl.exe boundary).
set -e
cd /home/lenovo2/t043_v2_diffusion
rm -rf postProcessing 1

cat > system/controlDict <<'EOF'
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
    Qin
    {
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        writeControl    writeTime;
        writeFields     no;
        log             yes;
        regionType      patch;
        name            inlet;
        operation       sum;
        fields          (phi);
    }
    wallHeatFlux1
    {
        type            wallHeatFlux;
        libs            ("libfieldFunctionObjects.so");
        executeControl  writeTime;
        writeControl    writeTime;
        writeFields     yes;
        patches         (walls);
    }
    Qwall
    {
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        writeControl    writeTime;
        writeFields     no;
        log             yes;
        regionType      patch;
        name            walls;
        operation       areaIntegrate;
        fields          (wallHeatFlux);
    }
}
EOF

source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1
scalarTransportFoam > log.energy 2>&1 || true
echo "=== energy log tail ==="
tail -5 log.energy
echo "=== inlet/outlet T and phi ==="
grep -E "areaAverage|sum\(|areaIntegrate" log.energy | head -12
echo "=== wallHeatFlux field written? ==="
ls 1/ 2>/dev/null
