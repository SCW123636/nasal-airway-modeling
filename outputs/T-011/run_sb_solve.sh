#!/bin/bash
# T-011 A.4 S-B solve. Trial run (endTime 2) to validate the dict first, per the
# task card ("S-B 本身未跑过，先 endTime 2 试启动验证 dict 再正式跑"), then the
# full 600-iteration run. Resumable: startFrom latestTime; FRESH=1 clears time dirs.
# Cross-session pkill hazard: if this run is killed by name, rerun WITHOUT FRESH
# and the previous full-attempt log is preserved as log.simpleFoam.attempt1.
CASE=/home/lenovo2/t011_p0/sb
STAGE=/home/lenovo2/t011_p0
source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1
cd "$CASE" || { echo "NO CASE DIR"; exit 1; }

banner() { echo; echo "== $* =="; }

banner "trial: endTime 600 -> 2 (dict validation only)"
grep -E "^endTime|^writeControl|^writeInterval" system/controlDict
sed -i 's/^endTime 600;/endTime 2;/' system/controlDict
simpleFoam > log.trial 2>&1
RC=$?
echo "trial exit=$RC"
grep -E "FOAM FATAL|^End" log.trial || true
tail -5 log.trial
if [ $RC -ne 0 ]; then
  sed -i 's/^endTime 2;/endTime 600;/' system/controlDict
  echo "TRIAL FAILED rc=$RC (endTime restored to 600)"; exit 1
fi
grep -q "^End" log.trial || { sed -i 's/^endTime 2;/endTime 600;/' system/controlDict; echo "TRIAL NO END MARKER"; exit 1; }
echo "TRIAL OK"

banner "full run: endTime back to 600, FRESH start"
sed -i 's/^endTime 2;/endTime 600;/' system/controlDict
grep -E "^endTime|^startFrom|^writeInterval" system/controlDict
if [ "${FRESH:-0}" = "1" ]; then
  for d in $(ls -d [0-9]* 2>/dev/null); do [ "$d" != "0" ] && rm -rf "$d"; done
fi
[ -f log.simpleFoam ] && mv -f log.simpleFoam log.simpleFoam.attempt1
echo "existing time dirs: $(ls -d [0-9]* 2>/dev/null | tr '\n' ' ')"

/usr/bin/time -v simpleFoam > log.simpleFoam 2>&1
RC=$?
echo "simpleFoam exit=$RC"
grep -E "Maximum resident set size|Elapsed \(wall" log.simpleFoam
tail -3 log.simpleFoam
grep -E "^End" log.simpleFoam || echo "NO-END-MARKER"
if [ $RC -ne 0 ]; then echo "SOLVE FAILED rc=$RC"; exit 1; fi

banner "post: wallShearStress + foamToVTK"
simpleFoam -postProcess -func wallShearStress -latestTime > log.wss 2>&1
echo "wss exit=$?"
foamToVTK -ascii -time 600 > log.foamToVTK 2>&1
VTKDIR=$(ls -d VTK/sb_*/ 2>/dev/null | tail -1)
echo "VTK dir: $VTKDIR"
# stage to BOTH WSL FS and the Windows scratch the VTK extractor reads
mkdir -p "$STAGE/out_sb" /mnt/c/ts_work/t011_p0/sb_out
cp "$VTKDIR/boundary/"*.vtp "$STAGE/out_sb/" 2>/dev/null || echo "no boundary vtp"
cp "$VTKDIR/internal.vtu" "$STAGE/out_sb/internal_600.vtu" 2>/dev/null || echo "no internal.vtu"
cp "$VTKDIR/boundary/"*.vtp /mnt/c/ts_work/t011_p0/sb_out/ 2>/dev/null || echo "no /mnt/c copy"
echo "SB-SOLVE-DONE"
