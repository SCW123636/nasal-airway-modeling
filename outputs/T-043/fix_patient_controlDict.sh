#!/bin/bash
# Fix patient case controlDict for scalarTransportFoam (previous python patch
# did not match the actual spacing). Runs INSIDE WSL.
set -e
D=/home/lenovo2/t043_b15_temp/system/controlDict
sed -i 's/^application .*/application     scalarTransportFoam;/' "$D"
sed -i 's/^startFrom .*/startFrom       startTime;/' "$D"
sed -i 's/^endTime .*/endTime         1;/' "$D"
sed -i '0,/^writeInterval /s/^writeInterval .*/writeInterval   1;/' "$D"
cat >> "$D" <<'EOF'

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
EOF
echo "=== controlDict key lines ==="
grep -E "^application|^startFrom|^endTime|^writeInterval" "$D" | head -5
echo "=== functions present ==="
grep -c "Tnostril" "$D"
