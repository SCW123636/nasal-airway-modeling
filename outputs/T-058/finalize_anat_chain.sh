#!/bin/bash
# T-058 anatomical-cut: post-chain pipeline (collect -> extract -> verify).
# Run AFTER all three chains report CHAIN-DONE in their chain.log.
#
#   1. collect   WSL case dirs -> Windows staging C:/ts_work/t058_chain_anat
#   2. metrics   delta-p / R / M2 four criteria -> metrics_t058_<case>_oroext.json
#   3. wss       wallShearStress -> force / median / max -> wss_t058_<case>.json
#   4. verify    six-part acceptance aggregate -> outputs/T-058/anat_chain_verification.json
#
# The cut convention string is recorded verbatim inside both extractor reports so
# the口径 is never ambiguous when these numbers are compared to the axial-cut
# baselines (T-054 for b15, T-047 for b01).
set -e
cd "D:/项目/鼻腔建模"
PY310="C:/Users/lenovo/AppData/Local/Programs/Python/Python310/python.exe"
ROOT="C:/ts_work/t058_chain_anat"
CUT="anatomical_oblique_perpendicular_to_local_airway_axis"

echo "== 1/4 collect (WSL -> Windows staging) =="
wsl.exe -d Ubuntu-22.04 -- bash -lc "bash /home/lenovo2/t058_chain_anat/collect_chain_anat.sh"

echo "== 2/4 metrics =="
for C in b15 b01 b02; do
  "$PY310" outputs/T-058/extract_metrics_case.py "$C" "$ROOT" "$CUT"
done

echo "== 3/4 wall shear stress =="
for C in b15 b01 b02; do
  "$PY310" outputs/T-058/extract_wss_case.py "$C" "$ROOT" "$CUT"
done

echo "== 4/4 verify =="
"$PY310" outputs/T-058/verify_anat_chain.py "$ROOT"
echo "FINALIZE-DONE"
