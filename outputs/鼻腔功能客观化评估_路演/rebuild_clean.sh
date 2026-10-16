#!/usr/bin/env bash
# 干净重建：清空后的空白母版 + 顺序追加 18 页（append 模式，不用 --page-index）
# 关键事实（2026-10-16 实测）：编辑器把 python-pptx 生成的空白页视为 0 页，
# `upsert-dsl` 只做「追加」。因此必须一次、顺序、只跑一遍。
set -u

export SWC_NATIVE_BINDING_CACHE="C:/Users/lenovo/.swc_native_cache"
SLIDEP="C:/Users/lenovo/.workbuddy/binaries/node/versions/22.22.2-6/slidep"
DECK="鼻腔功能客观化评估_路演.pptx"
BASE="http://127.0.0.1:39100"

cd "D:/项目/鼻腔建模/outputs/鼻腔功能客观化评估_路演" || exit 1
mkdir -p _render
LOG="_render/rebuild.log"
: > "$LOG"

clean() { grep -v -e 'NodeImageLoadService' -e 'DeprecationWarning' -e 'trace-deprecation'; }

for i in $(seq 1 18); do
  n=$(printf "%02d" "$i")
  f="slides/${n}.slide"
  echo "########## APPEND $n ##########" >> "$LOG"

  out=$("$SLIDEP" upsert-dsl "$DECK" --dsl-file "$f" --base-url "$BASE" 2>&1 | clean | tail -1)
  echo "UPSERT: $out" >> "$LOG"

  idx=$((i - 1))
  out=$("$SLIDEP" lint "$DECK" --dsl-file "$f" --page-index "$idx" --visual --base-url "$BASE" 2>&1 | clean | tail -1)
  echo "LINT: $out" >> "$LOG"

  out=$("$SLIDEP" screenshot "$DECK" --page-index "$idx" --out "./_render/p${n}.png" --base-url "$BASE" 2>&1 | clean | tail -1)
  echo "SHOT: $out" >> "$LOG"
  echo >> "$LOG"
done
echo "REBUILD DONE" >> "$LOG"
