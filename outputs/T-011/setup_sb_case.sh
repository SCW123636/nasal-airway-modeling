#!/bin/bash
# T-011 A.4 (-300 x maxh1.0 x S-B): assemble case by REUSING the A.1 snappy mesh.
# Only difference from A.1 (S-A): three numbers in fvSolution
#   nNonOrthogonalCorrectors 2->3, equations{U 0.7->0.6}, fields{p 0.3->0.2}
# Everything else (solvers, consistent yes, residualControl, schemes, controlDict)
# stays byte-identical so the config diff is exactly those three lines.
SRC=/home/lenovo2/t011_p0/snappy
SB=/home/lenovo2/t011_p0/sb

rm -rf "$SB"
mkdir -p "$SB"
cp -r "$SRC/constant" "$SB/constant"
rm -rf "$SB/constant/triSurface"          # mesh already built in polyMesh; STLs not needed
cp -r "$SRC/system" "$SB/system"
mkdir -p "$SB/0"
cp "$SRC/0/U" "$SRC/0/p" "$SB/0/"

sed -i 's/nNonOrthogonalCorrectors 2;/nNonOrthogonalCorrectors 3;/' "$SB/system/fvSolution"
sed -i 's/equations { U 0.7; }/equations { U 0.6; }/'                     "$SB/system/fvSolution"
sed -i 's/fields { p 0.3; }/fields { p 0.2; }/'                           "$SB/system/fvSolution"

echo "=== fvSolution diff (must be exactly 3 lines) ==="
diff "$SRC/system/fvSolution" "$SB/system/fvSolution"
echo "=== polyMesh present ==="
ls "$SB/constant/polyMesh/" | head -6
echo "=== 0/ fields ==="
ls "$SB/0/"
echo "SETUP-SB-DONE"
