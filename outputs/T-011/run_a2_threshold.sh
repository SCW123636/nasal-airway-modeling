#!/bin/bash
# T-011 A.2 threshold axis (-350 / -400) x maxh1.0(snappy L3) x S-A - geometry phase.
# Stage 4 with the surface builder's OWN --hu-max flag (no work/** edits), stage 5
# verbatim from the pipeline invocation, N6 re-checked with the project's gate_report.
# Landmarks (stage 3) are threshold-independent -> reused from work/06_auto_landmarks.
PY="C:/Users/lenovo/AppData/Local/Programs/Python/Python310/python.exe"
LIB="D:/项目/鼻腔建模/work/lib"
ROOT="D:/项目/鼻腔建模"
AXIS="C:/ts_work/t011_axis"
LM="$ROOT/work/06_auto_landmarks/p0/landmarks.json"

for T in -350 -400; do
  TAG=$(echo "$T" | tr -d '-')
  SURF="$AXIS/surfaces_t$TAG"
  OPEN="$AXIS/opening_t$TAG"
  echo "===== threshold $T : stage 4 surface ====="
  "$PY" -u "$LIB/batch27_surface.py" --cases p0 --hu-max "$T" --out "$SURF" || { echo "S4 FAILED t$TAG rc=$?"; exit 1; }
  "$PY" -c "import hashlib,sys;print('surface_sha256',hashlib.sha256(open(r'$SURF/p0/source_surface.vtp','rb').read()).hexdigest())"

  echo "===== threshold $T : stage 5 opening ====="
  "$PY" -u "$LIB/auto_opening_pipeline.py" --output "$OPEN" --proposals "$ROOT/work/06_auto_landmarks" --src "$SURF" --cases p0 --seed-mode roi --search-origin reviewed || { echo "S5 FAILED t$TAG rc=$?"; exit 1; }

  echo "===== threshold $T : N6 gate (project gate_report) ====="
  "$PY" "$ROOT/outputs/T-011/check_n6_t.py" "$OPEN/p0/p0.json" "$SURF/p0/source_surface.vtp" "$LM"
  echo "===== threshold $T done ====="
done
echo "A2-GEOMETRY-DONE"
