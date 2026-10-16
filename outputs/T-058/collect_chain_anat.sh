#!/bin/bash
# T-058 anatomical-cut: collect solver artefacts from the WSL case dirs back to the
# Windows staging dirs that the metric extractors read.
# Variables live inside this file only (never cross the wsl.exe boundary).
set -e
for P in b15 b01 b02; do
  cp -r "/home/lenovo2/t058_chain_anat/$P/foam_maxh1/postProcessing" \
        "/mnt/c/ts_work/t058_chain_anat/$P/"
  cp "/home/lenovo2/t058_chain_anat/$P/foam_maxh1/log.simpleFoam" \
     "/mnt/c/ts_work/t058_chain_anat/$P/"
  cp "/home/lenovo2/t058_chain_anat/$P/foam_maxh1/checkMesh.log" \
     "/mnt/c/ts_work/t058_chain_anat/$P/"
  cp "/home/lenovo2/t058_chain_anat/$P/maxh1.msh.mesh.json" \
     "/mnt/c/ts_work/t058_chain_anat/$P/"
  cp "/home/lenovo2/t058_chain_anat/$P/foam_maxh1/log.wss" \
     "/mnt/c/ts_work/t058_chain_anat/$P/" || true
  cp "/home/lenovo2/t058_chain_anat/$P/foam_maxh1/log.foamToVTK" \
     "/mnt/c/ts_work/t058_chain_anat/$P/" || true
  echo "collected $P"
done
echo COLLECT-DONE
