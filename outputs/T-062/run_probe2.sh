#!/usr/bin/env bash
# T-062 诊断探针 v2：并行跑 3 个求解器设置变体（各 100 迭代，热启动自 50:50 收敛解）。
source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1
for d in A_consno B_reltol0 C_consno_reltol0; do
  ( cd "/home/lenovo2/t062_probe2/$d" && simpleFoam > log.simpleFoam 2>&1 ) &
done
wait
echo "ALL_PROBE2_DONE"
for d in A_consno B_reltol0 C_consno_reltol0; do
  echo "== $d =="
  grep -c "^Time = " "/home/lenovo2/t062_probe2/$d/log.simpleFoam" || true
done
