#!/usr/bin/env bash
# 干净重建（正确用法）：
#   1) 母版必须是「编辑器认为是 0 页」的有效 pptx（build_empty_deck.py 生成）
#   2) 必须用 --page-index i 且 i 从 0 起严格 +1 递增（空文档上等于顺序填页）
#   3) 不能用默认追加模式——它在空文档上第 2 页即 off-by-one 越界
#   4) 全流程只跑一遍，绝不重跑某一页（重跑会追加成「上一代」页）
set -u

export SWC_NATIVE_BINDING_CACHE="C:/Users/lenovo/.swc_native_cache"
SLIDEP="C:/Users/lenovo/.workbuddy/binaries/node/versions/22.22.2-6/slidep"
DECK="鼻腔功能客观化评估_路演.pptx"
BASE="http://127.0.0.1:39100"

cd "D:/项目/鼻腔建模/outputs/鼻腔功能客观化评估_路演" || exit 1
mkdir -p _render
LOG="_render/rebuild2.log"
: > "$LOG"

clean() { grep -v -e 'NodeImageLoadService' -e 'DeprecationWarning' -e 'trace-deprecation'; }

for i in $(seq 0 17); do
  n=$(printf "%02d" $((i + 1)))
  f="slides/${n}.slide"
  echo "########## PAGE $n ##########" >> "$LOG"

  out=$("$SLIDEP" upsert-dsl "$DECK" --dsl-file "$f" --page-index "$i" --base-url "$BASE" 2>&1 | clean | tail -1)
  echo "UPSERT: $out" >> "$LOG"

  out=$("$SLIDEP" lint "$DECK" --dsl-file "$f" --page-index "$i" --visual --base-url "$BASE" 2>&1 | clean | tail -1)
  echo "LINT: $out" >> "$LOG"

  out=$("$SLIDEP" screenshot "$DECK" --page-index "$i" --out "./_render/p${n}.png" --base-url "$BASE" 2>&1 | clean | tail -1)
  echo "SHOT: $out" >> "$LOG"
  echo >> "$LOG"
done
echo "REBUILD2 DONE" >> "$LOG"
