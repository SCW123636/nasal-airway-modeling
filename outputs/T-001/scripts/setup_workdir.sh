#!/usr/bin/env bash
# 复制上一轮只读产物与诊断脚本到 native Linux FS（避免 /mnt/c 跑 OpenFOAM 卡死）。
set +u
SRC=/mnt/c/ts_work/mesh_tools/patient_mesh_20261013
W=$HOME/patient_cfd/t001_work
mkdir -p "$W/scripts"
cp "$SRC/b15_patient_maxh1_repaired.msh" "$W/"
cp "$SRC/b15_patient_maxh1.msh" "$W/"
cp /mnt/d/项目/鼻腔建模/outputs/T-001/analyze_sliver_cells.py "$W/scripts/"
cp /mnt/d/项目/鼻腔建模/outputs/T-001/audit_msh_boundary_faces.py "$W/scripts/"
# R3 所需：Netgen 生成脚本与 env（仅复制，不改源码）
cp /mnt/d/项目/鼻腔建模/work/lib/netgen_patient_mesh.py "$W/scripts/" 2>/dev/null || echo "netgen_patient_mesh.py copy: skipped"
cp "$SRC/../netgen_env.sh" "$W/scripts/" 2>/dev/null || cp /mnt/c/ts_work/mesh_tools/netgen_env.sh "$W/scripts/" 2>/dev/null || echo "netgen_env.sh copy: skipped"
echo "=== workdir ==="
ls -la "$W"
echo "=== scripts ==="
ls -la "$W/scripts"
echo "DONE"
