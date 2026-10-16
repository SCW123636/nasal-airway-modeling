#!/usr/bin/env bash
# T-062 b15 natural-split rerun daemon (takeover relaunch, 2026-10-16 ~17:53).
# Survival design: setsid + nohup inside WSL => immune to Windows-side client
# teardown. Three previous runs died exit=-15 when their launching session's
# client/process group went away (17:23:40 kill happened while WSL stayed up).
set -e
source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1

WORK=/home/lenovo2/t062_split
LOG="$WORK/daemon_b15.log"
MARKER="$WORK/CHAIN-DONE-b15"
DRIVER="/mnt/d/项目/鼻腔建模/outputs/T-062/run_patient_split_ratio.py"

# targeted cleanup: only simpleFoam whose cwd is inside t062_split (never blanket)
for pid in $(pgrep -x simpleFoam); do
  cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null || true)
  case "$cwd" in
    *t062_split*) echo "kill stale $pid ($cwd)"; kill "$pid" || true ;;
    *) echo "skip $pid ($cwd)" ;;
  esac
done
sleep 2
rm -f "$MARKER"
mkdir -p "$WORK"

cd /home/lenovo2
setsid nohup bash -c '
  source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1
  python3 "/mnt/d/项目/鼻腔建模/outputs/T-062/run_patient_split_ratio.py" \
    --case-root /home/lenovo2/t058_chain_anat \
    --work-dir /home/lenovo2/t062_split \
    --cases b15 --rho 1.2 --target-m3s 2.5e-4 \
    --seed-time-dir /home/lenovo2/t058_chain_anat/b15/foam_maxh1/600 \
    --end-time 600 --write-interval 200 \
    --p-tol-pa 0.05 --max-evals 6
  rc=$?
  echo "CHAIN-DONE b15 rc=$rc $(date -Is)" > /home/lenovo2/t062_split/CHAIN-DONE-b15
' < /dev/null >> "$LOG" 2>&1 &

echo "DAEMON_LAUNCHED pid=$!"
