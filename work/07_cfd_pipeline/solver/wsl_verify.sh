#!/usr/bin/env bash
# wsl_verify.sh — 小隼求解工程移植（网格缓存 / 流式状态 / latestTime 归档 / MPI 并行）一键验证
#
# 设计要点（每条都对应一个已发生的事故）:
#   1. 直接跑 Windows 工作区代码（经 /mnt/d 映射），不在 WSL 内留副本 → 消除部署漂移。
#      ROOT 必须同时含 solver/ 与 solver_reference/，否则 run_reference import 失败。
#   2. 三段各自的 run_manifest 跑完立刻转存 → 每段都会覆盖它，不转存只剩最后一段。
#   3. 输出同时写日志文件和终端，但**不用 exec > >(tee)**：
#      进程替换是异步的，脚本快速退出时 tee 尚未落盘就被杀，错误信息会整段丢失
#      （实测 HELLO_B 出来了、DONE_B 和日志尾巴全没了）。
#      改为每行同步 tee 一次。
#   4. 预检逐项打印、先打印后退出 → 出错时能直接看到是哪一项，而不是一片空白。
#
# 用法（推荐从 stdin 传入，避开 Windows→WSL 的中文路径参数传递）:
#   wsl.exe -d Ubuntu-22.04 -- bash -c 'cat > /tmp/wv.sh' < wsl_verify.sh
#   wsl.exe -d Ubuntu-22.04 -- bash /tmp/wv.sh [CASE_DIR] [NPROC]
set -u

WSL_ROOT_DEFAULT="/mnt/d/项目/鼻腔建模/work/07_cfd_pipeline"
CASE="${1:-$HOME/nasal_cfd_reference/poiseuille_v1912_verified/coarse}"
NPROC="${2:-4}"
ROOT="${3:-$WSL_ROOT_DEFAULT}"
OUTDIR="${4:-$WSL_ROOT_DEFAULT/reports}"
RUNNER="$ROOT/solver/run_openfoam_case.py"

# ---- 输出通道：先落盘再定义 say，任何后续失败都留得下痕迹 ----
mkdir -p "$OUTDIR" 2>/dev/null || OUTDIR="$HOME/mf_verify_out"
mkdir -p "$OUTDIR" || OUTDIR="$HOME/mf_verify_out"
mkdir -p "$OUTDIR"
STAMP=$(date +%Y%m%d-%H%M%S)
LOG="$OUTDIR/mf_verify_$STAMP.txt"
: > "$LOG"
say() { printf '%s\n' "$*" | tee -a "$LOG"; }

say "================ 环境 ================"
say "时间戳  : $STAMP"
say "算例    : $CASE"
say "并行核数: $NPROC"
say "代码根  : $ROOT"
say "执行器  : $RUNNER"
say "输出目录: $OUTDIR"
say "日志    : $LOG"

say ""
say "---- 预检（逐项，先打印再决定是否继续） ----"
FAIL=0
chk() {  # chk <标签> <路径>
  if [ -e "$2" ]; then say "  ok   $1 : $2"; else say "  FAIL $1 : $2"; FAIL=1; fi
}
chk "算例目录" "$CASE"
chk "执行器" "$RUNNER"
chk "缓存模块" "$ROOT/solver/mesh_cache.py"
chk "依赖模块目录" "$ROOT/solver_reference"
chk "依赖模块" "$ROOT/solver_reference/run_reference.py"
for t in blockMesh simpleFoam mpirun decomposePar reconstructPar; do
  if command -v "$t" >/dev/null 2>&1; then say "  ok   工具 $t : $(command -v "$t")"; else say "  缺   工具 $t"; fi
done
if command -v python3 >/dev/null 2>&1; then say "  ok   python3 : $(command -v python3)"; else say "  FAIL python3"; FAIL=1; fi
say "  CPU 核数: $(nproc 2>/dev/null || echo '?')"
say ""
if [ "$FAIL" -ne 0 ]; then
  say "预检未通过，停止。（缺 mpirun/decomposePar 只影响第 3 段，会自动回退串行）"
  exit 2
fi

export WM_PROJECT_DIR=/usr/share/openfoam
export FOAM_ETC=/usr/share/openfoam/etc
export WM_PROJECT_VERSION=v1912
# bashrc 引用了缺失脚本，且在 set -u 下遇到未定义变量会直接杀死非交互 shell
# （错误还被 >/dev/null 2>&1 吞掉，表现为脚本静默消失）。
# 实测 OpenFOAM 工具全在 /usr/bin，source 非必需；保留时必须先关掉 -u。
if [ -f /usr/share/openfoam/etc/bashrc ]; then
  set +u
  . /usr/share/openfoam/etc/bashrc >/dev/null 2>&1 || true
  set -u
fi
export PYTHONPATH="$ROOT/solver"
PY=python3

if ! "$PY" "$RUNNER" --help >/dev/null 2>&1; then
  say "!! 执行器导入失败，真实报错如下:"
  "$PY" "$RUNNER" --help 2>&1 | tee -a "$LOG"
  exit 2
fi
say "导入自检: ok"
say ""

pick() {  # pick <jsonfile> <key>
  "$PY" - "$1" "$2" <<'EOF'
import json,sys
try:
    with open(sys.argv[1],encoding='utf-8') as fh: d=json.load(fh)
    v=d.get(sys.argv[2],"<missing>")
    print(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else str(v))
except FileNotFoundError: print("<file-missing>")
except Exception: print("<parse-error>")
EOF
}

steps_of() {  # steps_of <run_manifest.json> -> blockMesh,checkMesh,...
  "$PY" - "$1" <<'EOF'
import json,sys
try:
    with open(sys.argv[1],encoding='utf-8') as fh: d=json.load(fh)
    print(",".join(s["command"][0] for s in d.get("steps",[])))
except Exception: print("<parse-error>")
EOF
}

step_times() {
  "$PY" - "$1" <<'EOF'
import json,sys
try:
    with open(sys.argv[1],encoding='utf-8') as fh: d=json.load(fh)
    print(", ".join("%s=%.2fs" % (s['command'][0], s.get('elapsed_seconds', -1)) for s in d.get('steps', [])))
except Exception: print("<parse-error>")
EOF
}

WORK="$HOME/mf_verify_work"
rm -rf "$WORK"; mkdir -p "$WORK"
cp -r "$CASE" "$WORK/case" || { say "拷贝算例失败"; exit 2; }
CASE_W="$WORK/case"
say "工作副本: $CASE_W （原算例不被修改）"
say ""

# 每段跑完立刻转存证据：下一段会覆盖 run_manifest.json
snapshot() {  # snapshot <stage> <seconds> <rc>
  cp "$CASE_W/run_manifest.json" "$OUTDIR/${STAMP}_$1_manifest.json" 2>/dev/null
  say "  exit=$3  耗时=$2s"
  say "  steps       = $(steps_of "$CASE_W/run_manifest.json")"
  say "  status      = $(pick "$CASE_W/run_manifest.json" execution_status)"
  say "  status_file = $(pick "$CASE_W/run_status.json" status)"
  say "  step_times  = $(step_times "$CASE_W/run_manifest.json")"
}

say "================ 1/3 冷跑（串行，写缓存） ================"
S1=$SECONDS
"$PY" "$RUNNER" --case "$CASE_W" \
  --steps blockMesh,checkMesh,simpleFoam,foamToVTK \
  --status-file run_status.json --archive-before-run 2>&1 | tee -a "$LOG"
RC1=${PIPESTATUS[0]}; T1=$((SECONDS-S1))
snapshot stage1 "$T1" "$RC1"
if [ -f "$CASE_W/mesh_cache.json" ]; then
  cp "$CASE_W/mesh_cache.json" "$OUTDIR/${STAMP}_stage1_meshcache.json"
  say "  mesh_cache: signature=$(pick "$CASE_W/mesh_cache.json" signature)"
  say "              recorded_at=$(pick "$CASE_W/mesh_cache.json" recorded_at)"
else
  say "  !! mesh_cache.json 未生成 → 暖跑不会命中（检查 log.checkMesh 是否 Mesh OK）"
fi
say ""

say "================ 2/3 暖跑（串行 + --skip-mesh-if-cached） ================"
S2=$SECONDS
"$PY" "$RUNNER" --case "$CASE_W" \
  --steps blockMesh,checkMesh,simpleFoam,foamToVTK \
  --status-file run_status.json --archive-before-run --skip-mesh-if-cached 2>&1 | tee -a "$LOG"
RC2=${PIPESTATUS[0]}; T2=$((SECONDS-S2))
snapshot stage2 "$T2" "$RC2"
say "  缓存文件仍在: $([ -f "$CASE_W/mesh_cache.json" ] && echo yes || echo no)  ← 归档不得移走它"
say "  跳过了网格步: $(steps_of "$CASE_W/run_manifest.json" | grep -q blockMesh && echo no || echo yes)"
say ""

say "================ 3/3 暖跑（--parallel $NPROC + 缓存） ================"
S3=$SECONDS
"$PY" "$RUNNER" --case "$CASE_W" \
  --steps blockMesh,checkMesh,simpleFoam,foamToVTK \
  --status-file run_status.json --archive-before-run --skip-mesh-if-cached --parallel "$NPROC" 2>&1 | tee -a "$LOG"
RC3=${PIPESTATUS[0]}; T3=$((SECONDS-S3))
snapshot stage3 "$T3" "$RC3"
say ""

"$PY" - "$OUTDIR/${STAMP}_summary.json" "$T1" "$T2" "$T3" "$RC1" "$RC2" "$RC3" "$NPROC" "$CASE" "$ROOT" <<'EOF' 2>&1 | tee -a "$LOG"
import json,sys
vals = sys.argv[1:]
if len(vals) != 10:
    raise SystemExit("summary arg count wrong: expected 10, got %d -> %r" % (len(vals), vals))
out,t1,t2,t3,rc1,rc2,rc3,nproc,case,root = vals
t1,t2,t3 = int(t1),int(t2),int(t3)
json.dump({"case": case, "code_root": root, "nproc": int(nproc),
           "stages": {
             "1_cold_serial":   {"seconds": t1, "exit": int(rc1)},
             "2_warm_serial":   {"seconds": t2, "exit": int(rc2)},
             "3_warm_parallel": {"seconds": t3, "exit": int(rc3)}},
           "speedup_warm_vs_cold": round(t1/t2, 3) if t2 else None,
           "speedup_parallel_vs_warm": round(t2/t3, 3) if t3 else None},
          open(out,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
print("summary written:", out)
EOF

say "================ 汇总 ================"
say "冷跑(串行)                 : ${T1}s  exit=$RC1"
say "暖跑(串行 + 缓存命中)      : ${T2}s  exit=$RC2"
say "暖跑(并行${NPROC} + 缓存命中)    : ${T3}s  exit=$RC3"
say "冷/暖加速比                : $([ "$T2" -gt 0 ] && echo "x$($PY -c "print(round($T1/$T2,3))")" || echo n/a)"
say "并行/串行加速比            : $([ "$T3" -gt 0 ] && echo "x$($PY -c "print(round($T2/$T3,3))")" || echo n/a)"
say ""
say "算例目录（归档目录应与缓存共存）:"
ls -1 "$CASE_W" 2>&1 | sed 's/^/  /' | tee -a "$LOG"
say ""
say "产物已落 Windows 盘（WSL 会话关闭后仍可读）:"
say "  日志     : $LOG"
say "  汇总 JSON: $OUTDIR/${STAMP}_summary.json"
ls -1 "$OUTDIR" 2>&1 | grep "$STAMP" | sed 's/^/  /' | tee -a "$LOG"
