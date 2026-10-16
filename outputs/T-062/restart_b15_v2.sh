#!/usr/bin/env bash
# T-062 步骤4：修正 controlDict writeInterval bug 后重启 b15 自然分流重跑。
# 只杀本会话在本 case 目录下的 simpleFoam（禁止 blanket pkill）。
set -e
source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1

for pid in $(pgrep -x simpleFoam); do
  cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null || true)
  case "$cwd" in
    *t062_patient_v2*) echo "kill $pid ($cwd)"; kill "$pid" || true ;;
    *) echo "skip $pid ($cwd)" ;;
  esac
done
sleep 3

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
cat /home/lenovo2/t062_patient_v2/patient_bc_switch_report_v2.json 2>/dev/null
