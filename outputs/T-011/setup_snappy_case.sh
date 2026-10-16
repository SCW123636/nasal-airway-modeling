#!/bin/bash
# T-011 A.1 (snappyHexMesh route) - case assembly.
#   /home/lenovo2/t011_p0/snappy/  <- background mesh + castellated/snapped mesh
# Keeps the b15 numeric setup verbatim (S-A laminar preset comes from
# b15_maxh1/system + constant) so the only difference from b15 is the mesher.
# Renames the short-domain outlet everywhere it appears in the templates.
CASE=/home/lenovo2/t011_p0/snappy
WIN=/mnt/c/ts_work/t011_p0/snappy/geometry
PROJ=/mnt/d/项目/鼻腔建模/outputs/T-011/snappy_case
B15=/home/lenovo2/patient_cfd/b15_maxh1

rm -rf "$CASE"
mkdir -p "$CASE/system" "$CASE/constant/triSurface" "$CASE/0"

cp "$WIN"/*.stl "$CASE/constant/triSurface/" || { echo "STL COPY FAILED"; exit 1; }
cp "$PROJ/system/blockMeshDict" "$PROJ/system/snappyHexMeshDict" "$CASE/system/" || exit 1
cp "$B15/system/controlDict" "$B15/system/fvSchemes" "$B15/system/fvSolution" "$CASE/system/" || exit 1
cp "$B15/constant/transportProperties" "$B15/constant/turbulenceProperties" "$CASE/constant/" || exit 1

sed -i 's/nasopharynx_outlet/oropharynx_truncation_outlet/g' "$CASE/system/"*
sed -i 's/nasopharynx_outlet/oropharynx_truncation_outlet/g' "$CASE/constant/"*

echo "--- case files ---"
find "$CASE" -type f | sort
echo "--- patch names in controlDict ---"
grep -oE 'nostril_L|nostril_R|oropharynx_truncation_outlet|wall' "$CASE/system/controlDict" | sort | uniq -c
echo "--- STL sizes ---"
ls -la "$CASE/constant/triSurface/"
echo "SETUP-DONE"
