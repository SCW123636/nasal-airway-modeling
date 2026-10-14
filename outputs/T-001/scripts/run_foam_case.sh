#!/usr/bin/env bash
# 在 native Linux FS 建 OpenFOAM case，跑 gmshToFoam + checkMesh -allGeometry -allTopology。
# 用法: run_foam_case.sh <msh绝对路径> <case名> <writePrecision|template>
# 结果: $HOME/patient_cfd/<case名>/ 下 checkMesh.log, gmshToFoam.log, constant/polyMesh/
#       并复制 checkMesh.log/gmshToFoam.log/boundary 到 /mnt/d/.../outputs/T-001/logs/
set +u
SRC=/mnt/c/ts_work/mesh_tools/patient_mesh_20261013
TEMPLATE=/mnt/c/ts_work/mesh_tools/gmsh_trial/foam_case
LOGD=/mnt/d/项目/鼻腔建模/outputs/T-001/logs
MSH="$1"
CASE="$2"
PREC="$3"
source /usr/share/openfoam/etc/bashrc
WORK="$HOME/patient_cfd/$CASE"
rm -rf "$WORK"
mkdir -p "$WORK/system" "$WORK/constant"
cp "$TEMPLATE"/system/* "$WORK/system/"
if [ "$PREC" != "template" ]; then
    sed -i "s/^writePrecision .*/writePrecision $PREC;/" "$WORK/system/controlDict"
fi
cp "$MSH" "$WORK/"
cd "$WORK"
gmshToFoam "$(basename "$MSH")" >gmshToFoam.log 2>&1
echo "gmshToFoam rc=$?"
checkMesh -allGeometry -allTopology >checkMesh.log 2>&1
echo "checkMesh rc=$?"
mkdir -p "$LOGD"
cp checkMesh.log gmshToFoam.log "$LOGD/"
cp constant/polyMesh/boundary "$LOGD/boundary.$CASE" 2>/dev/null || true
echo "=== grep summary ($CASE) ==="
grep -E 'cells:|tetrahedra:|boundary patches:|undefined faces|Cell determinant|determinant|interpolation weight|non-orthogonality|Max skewness|Failed|Mesh OK|edge length' checkMesh.log gmshToFoam.log || true
echo "DONE $CASE"
