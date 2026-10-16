#!/usr/bin/env bash
# 最终重建：母版须为「编辑器视为 0 页」的有效 pptx；--page-index i 从 0 严格 +1；
# 单遍执行，绝不重跑单页（重跑会追加成重复页）。
# 本版 lint 不带 --visual：只跑确定性布局规则（child-containment / no-overflow /
# zero-position / overlap / alignment），VLM 留白判定另起一遍。
set -u

export SWC_NATIVE_BINDING_CACHE="C:/Users/lenovo/.swc_native_cache"
SLIDEP="C:/Users/lenovo/.workbuddy/binaries/node/versions/22.22.2-6/slidep"
DECK="鼻腔功能客观化评估_路演.pptx"
BASE="http://127.0.0.1:39100"

cd "D:/项目/鼻腔建模/outputs/鼻腔功能客观化评估_路演" || exit 1
mkdir -p _render
LOG="_render/final.log"
: > "$LOG"

clean() { grep -v -e 'NodeImageLoadService' -e 'DeprecationWarning' -e 'trace-deprecation'; }

for i in $(seq 0 17); do
  n=$(printf "%02d" $((i + 1)))
  f="slides/${n}.slide"
  echo "########## PAGE $n ##########" >> "$LOG"

  out=$("$SLIDEP" upsert-dsl "$DECK" --dsl-file "$f" --page-index "$i" --base-url "$BASE" 2>&1 | clean | tail -1)
  echo "UPSERT: $out" >> "$LOG"

  out=$("$SLIDEP" lint "$DECK" --dsl-file "$f" --page-index "$i" --base-url "$BASE" 2>&1 | clean | tail -1)
  echo "LINT: $out" >> "$LOG"

  out=$("$SLIDEP" screenshot "$DECK" --page-index "$i" --out "./_render/p${n}.png" --base-url "$BASE" 2>&1 | clean | tail -1)
  echo "SHOT: $out" >> "$LOG"
  echo >> "$LOG"
done
echo "FINAL DONE" >> "$LOG"
