#!/usr/bin/env bash
# T-062 b15 eval_001 (lambda=0.52) post-600 VTK export pipeline.
# Fires the moment Time=600 lands, exports ASCII VTK on a read-only copy.
set -e
source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1
SRC=/home/lenovo2/t062_split/b15/eval_001
PREP=/home/lenovo2/t062_split/vtk_prep_b15

for i in $(seq 1 120); do
  if [ -d "$SRC/600" ]; then break; fi
  sleep 5
done
if [ ! -d "$SRC/600" ]; then echo "NO_600_DIR"; exit 1; fi
sleep 15   # let simpleFoam finish writing the final time dir

rm -rf "$PREP"
mkdir -p "$PREP"
cp -r "$SRC/constant" "$SRC/system" "$PREP/"
cp -r "$SRC/600" "$PREP/600"
cd "$PREP"
foamToVTK -ascii -time 600 > log.foamToVTK 2>&1
echo "VTK_EXPORT_DONE"
ls VTK/
