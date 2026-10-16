#!/usr/bin/env bash
# 4 分钟版（9 页 16:9）构建：空白母版 + 单遍 upsert，绝不重跑单页（见 README 约束）
set -u
export SWC_NATIVE_BINDING_CACHE="C:/Users/lenovo/.swc_native_cache"
SLIDEP="C:/Users/lenovo/.workbuddy/binaries/node/versions/22.22.2-6/slidep"
BASE="http://127.0.0.1:39100"
cd "D:/项目/鼻腔建模/outputs/鼻腔功能客观化评估_路演"
DECK="$PWD/鼻腔功能客观化评估_路演_4分钟16x9.pptx"
LOG="_render/build_4min.log"

: > "$LOG"
ok=0; fail=0
for i in $(seq 0 8); do
  n=$(printf "%02d" $((i+1)))
  echo "########## PAGE $n ##########" >> "$LOG"
  out=$("$SLIDEP" upsert-dsl "$DECK" --dsl-file "slides_4min/${n}.slide" --page-index "$i" --base-url "$BASE" 2>&1 | grep -v -e NodeImage -e Deprecation | tail -1)
  echo "UPSERT: $out" >> "$LOG"
  case "$out" in *'"ok":true'*) ok=$((ok+1));; *) fail=$((fail+1));; esac
  out=$("$SLIDEP" lint "$DECK" --dsl-file "slides_4min/${n}.slide" --page-index "$i" 2>&1 | grep -v -e NodeImage -e Deprecation | tail -1)
  echo "LINT: $out" >> "$LOG"
  out=$("$SLIDEP" screenshot "$DECK" --page-index "$i" --out "./_render/m4_p${n}.png" --base-url "$BASE" 2>&1 | grep -v -e NodeImage -e Deprecation | tail -1)
  echo "SHOT: $out" >> "$LOG"
done
echo "UPSERT ok:$ok fail:$fail" >> "$LOG"
echo "M4 DONE" >> "$LOG"
