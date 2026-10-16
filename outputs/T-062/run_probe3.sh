#!/usr/bin/env bash
# T-062 诊断探针 v3：并行跑 3 个候选设置（各 120 迭代，热启动自 50:50 收敛解）。
source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1
for d in D_strongrelax E_reltol1e4 F_no_reltol1e4; do
  ( cd "/home/lenovo2/t062_probe3/$d" && simpleFoam > log.simpleFoam 2>&1 ) &
done
wait
echo "ALL_PROBE3_DONE"
