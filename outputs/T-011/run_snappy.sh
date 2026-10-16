#!/bin/bash
# T-011 A.1 (snappyHexMesh route) - mesh build + basic checks.
# Runs INSIDE WSL. Explicit RC checks after every stage (no pipeline masking).
CASE=/home/lenovo2/t011_p0/snappy
source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1
cd "$CASE" || { echo "NO CASE DIR"; exit 1; }

echo "== step 1: blockMesh =="
blockMesh > log.blockMesh 2>&1
RC=$?
echo "blockMesh exit=$RC"
tail -4 log.blockMesh
[ $RC -ne 0 ] && { echo "BLOCKMESH FAILED"; exit 1; }

echo
echo "== step 2: snappyHexMesh (castellate + snap, -overwrite) =="
/usr/bin/time -v snappyHexMesh -overwrite > log.snappyHexMesh 2>&1
RC=$?
echo "snappyHexMesh exit=$RC"
grep -E "Maximum resident set size|Elapsed \(wall" log.snappyHexMesh
echo "--- snappy summary lines ---"
grep -nE "Cells:|cells:|Checking final mesh|Finished meshing|Layer|Failed|FOAM FATAL|FOAM Warning" \
     log.snappyHexMesh | tail -25
echo "--- tail ---"
tail -25 log.snappyHexMesh
if [ $RC -ne 0 ]; then echo "SNAPPY FAILED rc=$RC"; exit 1; fi

echo
echo "== step 3: checkMesh =="
checkMesh -allGeometry -allTopology > log.checkMesh 2>&1
grep -E "cells:|Mesh non-orthogonality|Max aspect ratio|Failed|OK\.|boundary faces|points:" \
     log.checkMesh | head -20

echo
echo "== step 4: final patches =="
grep -E "^\s{4}(nostril_L|nostril_R|oropharynx_truncation_outlet|wall)" constant/polyMesh/boundary
echo
echo "== step 5: patch areas (from snappy log surface summary) =="
grep -nE "Surface|area" log.snappyHexMesh | head -20
echo "SNAPPY-DONE"
