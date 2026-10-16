#!/usr/bin/env bash
# T-062 决定性探针 v4：
#   G_prelax0 : 与 eval_001 同配置（17.0 Pa / U,p,phi 种子 / consistent no / relTol 0.01 /
#               U 0.4 p 0.15 / nNonOrth 2），唯一改动 p relTol -> 0。
#               若 G 稳定到 600 步 => 生产配置采用 p relTol 0。
#   H_d600    : D 变体精确复刻（17.114 Pa / 600/ 全量种子 / relTol 0.01）但 endTime 600。
#               若 H 也发散 => relTol 0.01 根本不稳，D 的"稳定"只是 47 步短窗假象。
# 注意：禁止 blanket pkill；只杀 cwd 在 t062_* 下的求解。探针 writeInterval 50（发散检测足够）。
set -e
source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1
SRC=/home/lenovo2/t058_chain_anat/b15/foam_maxh1
ROOT=/home/lenovo2/t062_probe4
P="/mnt/d/项目/鼻腔建模/outputs/T-062/probe_setup2.py"

for pid in $(pgrep -x simpleFoam); do
  cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null || true)
  case "$cwd" in
    /home/lenovo2/t062_*) echo "kill $pid ($cwd)"; kill "$pid" || true ;;
    *) echo "skip $pid ($cwd)" ;;
  esac
done
sleep 2

rm -rf "$ROOT"
for d in G_prelax0 H_d600; do
  mkdir -p "$ROOT/$d"
  cp -r "$SRC/constant" "$ROOT/$d/constant"
  cp -r "$SRC/system"   "$ROOT/$d/system"
  cp -r "$SRC/600"      "$ROOT/$d/0"
done

python3 "$P" --case "$ROOT/G_prelax0" --pressure-pa 17.0 --end-time 600 --write-interval 50 \
    --consistent no --reltol 0.01 --u-relax 0.4 --p-relax 0.15
sed -i "/solver GAMG/ s/relTol 0.01/relTol 0/" "$ROOT/G_prelax0/system/fvSolution"

python3 "$P" --case "$ROOT/H_d600" --pressure-pa 17.114 --end-time 600 --write-interval 50 \
    --consistent no --reltol 0.01 --u-relax 0.4 --p-relax 0.15

echo "=== G fvSolution ==="; grep -E "solver GAMG|smoothSolver" "$ROOT/G_prelax0/system/fvSolution"
echo "=== H fvSolution ==="; grep -E "solver GAMG|smoothSolver" "$ROOT/H_d600/system/fvSolution"
echo "BUILD_PROBE4_DONE"
