#!/usr/bin/env bash
# T-062 诊断探针 v3：找「稳定且便宜」的求解器设置。
# 先杀掉已判定发散的 A(consistent no/relTol0.01) 与 B(consistent yes/relTol0)。
set -e
SRC=/home/lenovo2/t058_chain_anat/b15/foam_maxh1
ROOT=/home/lenovo2/t062_probe3
P="/mnt/d/项目/鼻腔建模/outputs/T-062/probe_setup2.py"

for pid in $(pgrep -x simpleFoam); do
  cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null || true)
  case "$cwd" in
    *A_consno*|*B_reltol0*) echo "kill $pid ($cwd)"; kill "$pid" || true ;;
  esac
done

rm -rf "$ROOT"
for d in D_strongrelax E_reltol1e4 F_no_reltol1e4; do
  mkdir -p "$ROOT/$d"
  cp -r "$SRC/constant" "$ROOT/$d/constant"
  cp -r "$SRC/system"   "$ROOT/$d/system"
  cp -r "$SRC/600"      "$ROOT/$d/0"
done

python3 "$P" --case "$ROOT/D_strongrelax" --pressure-pa 17.114 --end-time 120 \
    --consistent no --reltol 0.01 --u-relax 0.4 --p-relax 0.15
python3 "$P" --case "$ROOT/E_reltol1e4" --pressure-pa 17.114 --end-time 120 \
    --consistent yes --reltol 1e-4
python3 "$P" --case "$ROOT/F_no_reltol1e4" --pressure-pa 17.114 --end-time 120 \
    --consistent no --reltol 1e-4 --u-relax 0.7 --p-relax 0.3

echo "=== D ==="; grep -E "consistent|relTol|nNonOrth" "$ROOT/D_strongrelax/system/fvSolution"; grep -E "relaxationFactors" -A3 "$ROOT/D_strongrelax/system/fvSolution" | tail -4
echo "=== E ==="; grep -E "consistent|relTol|nNonOrth" "$ROOT/E_reltol1e4/system/fvSolution"; grep -E "relaxationFactors" -A3 "$ROOT/E_reltol1e4/system/fvSolution" | tail -4
echo "=== F ==="; grep -E "consistent|relTol|nNonOrth" "$ROOT/F_no_reltol1e4/system/fvSolution"; grep -E "relaxationFactors" -A3 "$ROOT/F_no_reltol1e4/system/fvSolution" | tail -4
