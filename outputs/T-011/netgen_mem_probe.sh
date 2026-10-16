#!/bin/bash
# T-011 netgen memory probe: run netgen_patient_mesh_t047.py with given size
# parameters, sample RSS every 15 s, and hard-kill once it passes a ceiling so a
# hopeless run costs ~1 min instead of 15. Prints a memory curve + peak.
#   usage: netgen_mem_probe.sh <stl> <export.json> <maxh> <grading> <ceiling_MB> <tag>
STL=$1; EXPORT=$2; MAXH=$3; GRAD=$4; CEIL=${5:-9500}; TAG=${6:-probe}; EXTRAS=${7:-}
P=/home/lenovo2/netgen_venv/bin/python
S=/home/lenovo2/patient_cfd/t054_b15_oroext/netgen_patient_mesh_t047.py
if [ -n "$EXTRAS" ]; then
  S=/home/lenovo2/patient_cfd/t054_b15_oroext/netgen_patient_mesh_t047_minh.py
fi
cd /home/lenovo2/t011_p0 || exit 1
OUT=ng_${TAG}.msh
echo "== probe $TAG: maxh=$MAXH grading=$GRAD extras='$EXTRAS' ceiling=${CEIL}MB =="
$P "$S" "$STL" "$EXPORT" "$OUT" --maxh "$MAXH" --grading "$GRAD" $EXTRAS > "ng_${TAG}.log" 2>&1 &
PID=$!
peak=0
for i in $(seq 1 40); do
  sleep 15
  RSS=$(ps -o rss= -p $PID 2>/dev/null | tr -d ' ')
  if [ -z "$RSS" ]; then echo "t=$((i*15))s  EXITED (see ng_${TAG}.log)"; break; fi
  MB=$((RSS/1024))
  [ $MB -gt $peak ] && peak=$MB
  echo "t=$((i*15))s  RSS=${MB} MB"
  if [ $MB -gt $CEIL ]; then echo "CEILING HIT -> kill -9"; kill -9 $PID; break; fi
done
echo "PEAK_RSS_MB=$peak  TAG=$TAG"
ls -la "$OUT" 2>/dev/null || echo "no output mesh"
