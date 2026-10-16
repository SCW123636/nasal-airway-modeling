#!/usr/bin/env bash
# T-062 b15 分流比外层自然分流（替代压力驱动路线）。
# 注意：不得 blanket pkill —— t011_axis 下有其他会话的求解在跑。
set -e
source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1

python3 "/mnt/d/项目/鼻腔建模/outputs/T-062/run_patient_split_ratio.py" \
  --case-root /home/lenovo2/t058_chain_anat \
  --work-dir /home/lenovo2/t062_split \
  --cases b15 --rho 1.2 --target-m3s 2.5e-4 \
  --seed-time-dir /home/lenovo2/t058_chain_anat/b15/foam_maxh1/600 \
  --end-time 600 --write-interval 200 \
  --p-tol-pa 0.05 --max-evals 6

echo "T062_SPLIT_B15_DONE"
head -80 /home/lenovo2/t062_split/patient_split_ratio_report.json
