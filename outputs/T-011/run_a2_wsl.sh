#!/bin/bash
# T-011 A.2 threshold axis - assemble + mesh (snappy L3) + solve (S-A) per threshold.
# Mirrors the A.1 chain byte-for-byte EXCEPT:
#   - STLs come from this threshold's opening surface (t350 / t400)
#   - locationInMesh is this surface's measured interior point (split report, mm -> m)
# blockMeshDict / snappyHexMeshDict(refinement) / controlDict / fvSolution / fvSchemes
# are copied VERBATIM from the A.1 case (bbox check: both surfaces inside the A.1 box).
# Usage: bash run_a2_wsl.sh <tag>   with tag in {t350, t400}
TAG="$1"
case "$TAG" in
  t350) LIM="(-0.01188386 -0.15724868 -0.66226915)";;   # split report t350, clearance 6.49 mm
  t400) LIM="(-0.01188386 -0.15724868 -0.66231388)";;   # split report t400, clearance 6.46 mm
  *) echo "BAD TAG $TAG"; exit 1;;
esac
CASE=/home/lenovo2/t011_axis/$TAG
SRC_A1=/home/lenovo2/t011_p0/snappy
GEO_WIN=/mnt/c/ts_work/t011_axis/snappy_$TAG/geometry
source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1

echo "===== $TAG : assemble ====="
rm -rf "$CASE"
mkdir -p "$CASE/system" "$CASE/constant/triSurface" "$CASE/0"
cp "$GEO_WIN"/*.stl "$CASE/constant/triSurface/" || { echo "STL COPY FAILED"; exit 1; }
for f in nostril_L nostril_R oropharynx_truncation_outlet wall; do
  surfaceTransformPoints -scale '(0.001 0.001 0.001)' \
    "$CASE/constant/triSurface/$f.stl" \
    "$CASE/constant/triSurface/$f.stl" > /dev/null 2>&1
  RC=$?
  echo "scale $f rc=$RC"
  [ $RC -ne 0 ] && { echo "SCALE FAILED $f"; exit 1; }
done
cp "$SRC_A1/system/blockMeshDict" "$SRC_A1/system/snappyHexMeshDict" \
   "$SRC_A1/system/controlDict" "$SRC_A1/system/fvSchemes" "$SRC_A1/system/fvSolution" \
   "$CASE/system/" || { echo "DICT COPY FAILED"; exit 1; }
cp "$SRC_A1/constant/transportProperties" "$SRC_A1/constant/turbulenceProperties" \
   "$CASE/constant/" || { echo "CONST COPY FAILED"; exit 1; }
cp "$SRC_A1/0/U" "$SRC_A1/0/p" "$CASE/0/" || { echo "0/ COPY FAILED"; exit 1; }
sed -i "s|locationInMesh .*;|locationInMesh $LIM;|" "$CASE/system/snappyHexMeshDict"
grep -n "locationInMesh" "$CASE/system/snappyHexMeshDict"

cd "$CASE" || exit 1

echo "===== $TAG : blockMesh ====="
blockMesh > log.blockMesh 2>&1
RC=$?
echo "blockMesh exit=$RC"
[ $RC -ne 0 ] && { tail -5 log.blockMesh; echo "BLOCKMESH FAILED"; exit 1; }

echo "===== $TAG : snappyHexMesh ====="
/usr/bin/time -v snappyHexMesh -overwrite > log.snappyHexMesh 2>&1
RC=$?
grep -E "Maximum resident set size|Elapsed \(wall" log.snappyHexMesh
tail -3 log.snappyHexMesh
[ $RC -ne 0 ] && { echo "SNAPPY FAILED rc=$RC"; exit 1; }

echo "===== $TAG : checkMesh ====="
checkMesh -allGeometry -allTopology > log.checkMesh 2>&1
grep -E "cells:|Mesh non-orthogonality|Max aspect ratio|Number of regions|Total volume|Failed|concave" log.checkMesh | head -12

echo "===== $TAG : solve S-A (endTime 600) ====="
/usr/bin/time -v simpleFoam > log.simpleFoam 2>&1
RC=$?
echo "simpleFoam exit=$RC"
grep -E "Maximum resident set size|Elapsed \(wall" log.simpleFoam
tail -3 log.simpleFoam
grep -E "^End" log.simpleFoam || echo "NO-END-MARKER"
[ $RC -ne 0 ] && { echo "SOLVE FAILED rc=$RC"; exit 1; }

echo "===== $TAG : post (wss + foamToVTK) ====="
simpleFoam -postProcess -func wallShearStress -latestTime > log.wss 2>&1
echo "wss exit=$?"
foamToVTK -ascii -time 600 > log.foamToVTK 2>&1
VTKDIR=$(ls -d VTK/${TAG}_*/ 2>/dev/null | tail -1)
echo "VTK dir: $VTKDIR"
mkdir -p /mnt/c/ts_work/t011_axis/out_$TAG
cp "$VTKDIR/boundary/"*.vtp /mnt/c/ts_work/t011_axis/out_$TAG/ 2>/dev/null || echo "no boundary vtp"
echo "patch nFaces:"
grep -E "^\s+(nostril_L|nostril_R|oropharynx_truncation_outlet|wall)\s*$" -A1 constant/polyMesh/boundary | grep nFaces
echo "A2-$TAG-DONE"
