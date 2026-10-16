#!/usr/bin/env bash
# 全 18 页 upsert + 视觉 lint + 截图；结果写入 _render/build.log
set -u

export SWC_NATIVE_BINDING_CACHE="C:/Users/lenovo/.swc_native_cache"
SLIDEP="C:/Users/lenovo/.workbuddy/binaries/node/versions/22.22.2-6/slidep"
DECK="鼻腔功能客观化评估_路演.pptx"
BASE="http://127.0.0.1:39100"

cd "D:/项目/鼻腔建模/outputs/鼻腔功能客观化评估_路演" || exit 1
mkdir -p _render
LOG="_render/build.log"
: > "$LOG"

clean() { grep -v -e 'NodeImageLoadService' -e 'DeprecationWarning' -e 'trace-deprecation'; }

for i in $(seq 0 17); do
  n=$(printf "%02d" $((i + 1)))
  f="slides/${n}.slide"
  if [ ! -f "$f" ]; then echo "MISSING $f" >> "$LOG"; continue; fi

  echo "########## PAGE $n (index $i) ##########" >> "$LOG"

  out=$("$SLIDEP" upsert-dsl "$DECK" --dsl-file "$f" --page-index "$i" --base-url "$BASE" 2>&1 | clean | tail -1)
  echo "UPSERT: $out" >> "$LOG"

  out=$("$SLIDEP" lint "$DECK" --dsl-file "$f" --page-index "$i" --visual --base-url "$BASE" 2>&1 | clean | tail -1)
  echo "LINT: $out" >> "$LOG"

  out=$("$SLIDEP" screenshot "$DECK" --page-index "$i" --out "./_render/p${n}.png" --base-url "$BASE" 2>&1 | clean | tail -1)
  echo "SHOT: $out" >> "$LOG"
  echo >> "$LOG"
done

echo "ALL DONE" >> "$LOG"
