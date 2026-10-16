#!/usr/bin/env bash
# T-062 b15 split-ratio rerun: launch daemon AND hold the wsl.exe client open.
# The holding client is the real keep-alive: WSL2 VM shuts down ~8s after the
# last client disconnects, which SIGTERMs everything inside (root cause of the
# three exit=-15 deaths). This script must run as a WorkBuddy background task.
set -u
bash "/mnt/d/项目/鼻腔建模/outputs/T-062/daemon_b15_split.sh"
MARKER=/home/lenovo2/t062_split/CHAIN-DONE-b15
LOG=/home/lenovo2/t062_split/daemon_b15.log
for i in $(seq 1 780); do
  if [ -f "$MARKER" ]; then
    echo "=== CHAIN-DONE ==="
    cat "$MARKER"
    echo "=== report (cases.b15 head) ==="
    python3 - << 'PYEOF'
import json
d = json.load(open("/home/lenovo2/t062_split/patient_split_ratio_report.json"))
b15 = d["cases"].get("b15", {})
print(json.dumps({"status": b15.get("status"),
                  "best": {k: b15.get("best", {}).get(k) for k in
                           ("lambda_left", "p_left_pa", "p_right_pa", "p_common_pa",
                            "q_total_m3_s", "left_fraction", "converged")},
                  "n_evals": len(b15.get("evaluations", []))},
                 ensure_ascii=False, indent=1))
PYEOF
    exit 0
  fi
  if ! pgrep -f run_patient_split_ratio.py >/dev/null 2>&1; then
    sleep 10
    if [ -f "$MARKER" ]; then
      echo "=== CHAIN-DONE (late write) ==="; cat "$MARKER"; exit 0
    fi
    echo "=== DAEMON DIED without marker ==="
    tail -30 "$LOG"
    exit 1
  fi
  sleep 60
done
echo "=== TIMEOUT 13h ==="
tail -30 "$LOG"
exit 2
