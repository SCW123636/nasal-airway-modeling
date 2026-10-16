#!/usr/bin/env bash
# T-062 决定性探针 v4 并行求解：G（p relTol 0）与 H（D 复刻 600 步）。
set -e
source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1
ROOT=/home/lenovo2/t062_probe4

( cd "$ROOT/G_prelax0" && simpleFoam > log.simpleFoam 2>&1; echo "G_EXIT=$?" ) &
GPID=$!
( cd "$ROOT/H_d600" && simpleFoam > log.simpleFoam 2>&1; echo "H_EXIT=$?" ) &
HPID=$!
wait $GPID
wait $HPID

echo "=== G tail ==="; tail -3 "$ROOT/G_prelax0/log.simpleFoam"
echo "=== H tail ==="; tail -3 "$ROOT/H_d600/log.simpleFoam"
echo "RUN_PROBE4_DONE"
