#!/usr/bin/env bash
# T-006 Run 1 续跑包装器（detached）
# 起因：2026-10-14 18:38 首个 simpleFoam 进程被外部终止（Time=533，无求解器报错）。
# 本包装器：从 latestTime 续跑 + 独立同步日志到 Windows 侧，避免再被会话回收连带杀死。
# 注意：不可用 set -e/-u —— OpenFOAM etc/bashrc 在源入时引用未绑定变量，会立即中止脚本。
C=/home/lenovo2/patient_cfd/t004_diag
D="/mnt/d/项目/鼻腔建模/outputs/T-006/logs"
NS="flow_nostril_L flow_nostril_R flow_nasopharynx_outlet pressure_nostril_L pressure_nostril_R pressure_nasopharynx_outlet"

source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1
echo "bashrc sourced, WM_PROJECT_VERSION=${WM_PROJECT_VERSION:-UNKNOWN}, foamDictionary=$(command -v foamDictionary)" >> "$D/wrapper_debug.txt"

cd "$C" || { echo "cd failed" >> "$D/wrapper_debug.txt"; exit 1; }

sync_once() {
  cp -f "$C/log.simpleFoam" "$D/log.simpleFoam" 2>/dev/null
  for n in $NS; do
    mkdir -p "$D/postProcessing/$n/0"
    cp -f "$C/postProcessing/$n/0/surfaceFieldValue.dat" "$D/postProcessing/$n/0/surfaceFieldValue.dat" 2>/dev/null
    cp -f "$C/postProcessing/$n/0/surfaceFieldValue_0.dat" "$D/postProcessing/$n/0/surfaceFieldValue_0.dat" 2>/dev/null
    mkdir -p "$D/postProcessing/$n/400"
    cp -f "$C/postProcessing/$n/400/surfaceFieldValue_400.dat" "$D/postProcessing/$n/400/surfaceFieldValue_400.dat" 2>/dev/null
  done
}

mkdir -p "$D"

(
  while true; do
    sleep 180
    sync_once
    pgrep -x simpleFoam >/dev/null 2>&1 || { sync_once; break; }
  done
) &
SYNC=$!

echo "=== T-006 resume: simpleFoam start at $(date) (from latestTime, endTime 1500) ===" >> "$D/run_events.txt"

simpleFoam > log.simpleFoam 2>&1
rc=$?
echo "=== simpleFoam exited rc=$rc at $(date) ===" >> log.simpleFoam
echo "=== T-006 resume: simpleFoam exited rc=$rc at $(date) ===" >> "$D/run_events.txt"
sync_once
kill $SYNC 2>/dev/null
echo "wrapper done rc=$rc at $(date)" >> "$D/run_events.txt"
