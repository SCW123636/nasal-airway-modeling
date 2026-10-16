#!/usr/bin/env bash
# T-062 步骤4：b15 自然分流重跑（v2 驱动）。endTime=600 与 T-058 生产链一致。
set -e
source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1

# 注意：禁止 blanket `pkill -x simpleFoam` —— 会误杀其它会话（T-011 曾中招）。
# 探针已在 launch 前逐 PID 清理完毕，此处不再清理。
echo "simpleFoam now running: $(pgrep -x simpleFoam | wc -l)"

rm -rf /home/lenovo2/t062_patient_v2
mkdir -p /home/lenovo2/t062_patient_v2

python3 "/mnt/d/项目/鼻腔建模/outputs/T-062/run_patient_bc_switch_v2.py" \
  --case-root /home/lenovo2/t058_chain_anat \
  --work-dir  /home/lenovo2/t062_patient_v2 \
  --cases b15 --rho 1.2 --target-m3s 2.5e-4 \
  --initial-pressure-pa 17.0 \
  --seed-time-dir /home/lenovo2/t058_chain_anat/b15/foam_maxh1/600 \
  --end-time 600 --write-interval 200

echo "T062_B15_DRIVER_DONE"
cat /home/lenovo2/t062_patient_v2/patient_bc_switch_report_v2.json 2>/dev/null | head -60
