#!/usr/bin/env bash
# T-062 诊断探针 v2：搭建 3 个求解器设置变体 case（以生产 50:50 收敛解为初场）。
set -e
SRC=/home/lenovo2/t058_chain_anat/b15/foam_maxh1
ROOT=/home/lenovo2/t062_probe2
rm -rf "$ROOT"
for d in A_consno B_reltol0 C_consno_reltol0; do
  mkdir -p "$ROOT/$d"
  cp -r "$SRC/constant" "$ROOT/$d/constant"
  cp -r "$SRC/system"   "$ROOT/$d/system"
  cp -r "$SRC/600"      "$ROOT/$d/0"
done
ls -la "$ROOT"
ls -la "$ROOT/A_consno"
ls -la "$ROOT/A_consno/system"
ls -la "$ROOT/A_consno/0" | head -8
