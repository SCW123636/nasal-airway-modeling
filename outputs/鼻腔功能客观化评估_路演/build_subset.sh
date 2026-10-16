#!/usr/bin/env bash
# 按传入的 page index 列表重跑 upsert + 视觉 lint + 截图
# 用法：bash build_subset.sh 0 7 9 10 14 16
set -u

export SWC_NATIVE_BINDING_CACHE="C:/Users/lenovo/.swc_native_cache"
SLIDEP="C:/Users/lenovo/.workbuddy/binaries/node/versions/22.22.2-6/slidep"
DECK="鼻腔功能客观化评估_路演.pptx"
BASE="http://127.0.0.1:39100"

cd "D:/项目/鼻腔建模/outputs/鼻腔功能客观化评估_路演" || exit 1
mkdir -p _render
LOG="_render/build_subset.log"
: > "$LOG"

clean() { grep -v -e 'NodeImageLoadService' -e 'DeprecationWarning' -e 'trace-deprecation'; }

for i in "$@"; do
  n=$(printf "%02d" $((i + 1)))
  f="slides/${n}.slide"
  echo "########## PAGE $n (index $i) ##########" >> "$LOG"
  out=$("$SLIDEP" upsert-dsl "$DECK" --dsl-file "$f" --page-index "$i" --base-url "$BASE" 2>&1 | clean | tail -1)
  echo "UPSERT: $out" >> "$LOG"
  out=$("$SLIDEP" lint "$DECK" --dsl-file "$f" --page-index "$i" --visual --base-url "$BASE" 2>&1 | clean | tail -1)
  echo "LINT: $out" >> "$LOG"
  out=$("$SLIDEP" screenshot "$DECK" --page-index "$i" --out "./_render/p${n}.png" --base-url "$BASE" 2>&1 | clean | tail -1)
  echo "SHOT: $out" >> "$LOG"
  echo >> "$LOG"
done
echo "SUBSET DONE" >> "$LOG"
