#!/usr/bin/env bash
# T-062 诊断探针 v2：为 3 个变体写入自然分流 BC + 求解器设置。
set -e
S="/mnt/d/项目/鼻腔建模/outputs/T-062/probe_setup2.py"
python3 "$S" --case /home/lenovo2/t062_probe2/A_consno          --pressure-pa 17.114 --end-time 100 --consistent no
python3 "$S" --case /home/lenovo2/t062_probe2/B_reltol0         --pressure-pa 17.114 --end-time 100 --reltol 0
python3 "$S" --case /home/lenovo2/t062_probe2/C_consno_reltol0  --pressure-pa 17.114 --end-time 100 --consistent no --reltol 0
echo "=== A ==="; grep -E "consistent|nNonOrth|relTol" /home/lenovo2/t062_probe2/A_consno/system/fvSolution
echo "=== B ==="; grep -E "consistent|nNonOrth|relTol" /home/lenovo2/t062_probe2/B_reltol0/system/fvSolution
echo "=== C ==="; grep -E "consistent|nNonOrth|relTol" /home/lenovo2/t062_probe2/C_consno_reltol0/system/fvSolution
