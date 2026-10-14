#!/usr/bin/env bash
# 网格主导场景下的缓存收益测量：blockMesh+checkMesh 各跑一次，第二次带 --skip-mesh-if-cached
set -u
BIG="$HOME/mf_bigmesh"
SRC="$HOME/nasal_cfd_reference/poiseuille_v1912_verified/coarse"
R="/mnt/d/项目/鼻腔建模/work/07_cfd_pipeline"

export WM_PROJECT_DIR=/usr/share/openfoam
export FOAM_ETC=/usr/share/openfoam/etc
export WM_PROJECT_VERSION=v1912
export PYTHONPATH="$R/solver"
PY=python3

rm -rf "$BIG"
mkdir -p "$BIG/system" "$BIG/constant" "$BIG/0"
cp "$SRC"/system/fvSchemes "$SRC"/system/fvSolution "$SRC"/system/controlDict "$BIG/system/"
cp "$SRC"/0/U "$SRC"/0/p "$BIG/0/"
cp "$SRC"/constant/transportProperties "$SRC"/constant/turbulenceProperties "$BIG/constant/"

cat > "$BIG/system/blockMeshDict" <<'DICT'
FoamFile { version 2.0; format ascii; class dictionary; object blockMeshDict; }
convertToMeters 1;
vertices ( (0 0 0) (0.04 0 0) (0.04 0.002 0) (0 0.002 0) (0 0 0.001) (0.04 0 0.001) (0.04 0.002 0.001) (0 0.002 0.001) );
blocks ( hex (0 1 2 3 4 5 6 7) (300 100 20) simpleGrading (1 1 1) );
edges ();
boundary
(
 inlet { type patch; faces ((0 4 7 3)); }
 outlet { type patch; faces ((1 2 6 5)); }
 walls { type wall; faces ((0 1 5 4) (3 7 6 2)); }
 frontAndBack { type empty; faces ((0 3 2 1) (4 5 6 7)); }
);
mergePatchPairs ();
DICT

echo "网格规模: 300 x 100 x 20 = 600000 cells"

S=$SECONDS
"$PY" "$R/solver/run_openfoam_case.py" --case "$BIG" \
  --steps blockMesh,checkMesh --status-file run_status.json > /tmp/big_cold.json 2>&1
RC1=$?; T1=$((SECONDS-S))
echo ""
echo "冷跑(含 blockMesh+checkMesh): ${T1}s  rc=$RC1"
grep -E '"command"|elapsed' /tmp/big_cold.json | head -8
echo "缓存已记录: $([ -f "$BIG/mesh_cache.json" ] && echo yes || echo no)"
# 暖跑会覆盖 run_manifest.json，冷跑的逐步耗时必须现在快照
cp "$BIG/run_manifest.json" /tmp/big_cold_mf.json

S=$SECONDS
"$PY" "$R/solver/run_openfoam_case.py" --case "$BIG" \
  --steps blockMesh,checkMesh --status-file run_status.json --skip-mesh-if-cached > /tmp/big_warm.json 2>&1
RC2=$?; T2=$((SECONDS-S))
echo ""
echo "暖跑(--skip-mesh-if-cached): ${T2}s  rc=$RC2"
grep -E '"command"|elapsed|mesh_skipped' /tmp/big_warm.json | head -8
cp "$BIG/run_manifest.json" /tmp/big_warm_mf.json
echo ""
if [ "$T2" -gt 0 ]; then
  echo "缓存加速比: x$($PY -c "print(round($T1/$T2,2))")"
else
  echo "缓存加速比: n/a (T2=0)"
fi

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="/mnt/d/项目/鼻腔建模/work/07_cfd_pipeline/reports/bigmesh_cache_$STAMP.json"
mkdir -p "$(dirname "$OUT")"
"$PY" - "$OUT" "$T1" "$T2" "$RC1" "$RC2" /tmp/big_cold_mf.json /tmp/big_warm_mf.json <<'EOF'
import json,sys
vals=sys.argv[1:]
if len(vals)!=7:
    raise SystemExit("arg count wrong: %r" % (vals,))
out,t1,t2,rc1,rc2,cold_mf,warm_mf=vals
t1,t2=int(t1),int(t2)
def steps(path):
    """elapsed_seconds lives in run_manifest.json, not in the stdout summary."""
    try:
        with open(path,encoding='utf-8') as fh: d=json.load(fh)
        return {s['command'][0]: round(s.get('elapsed_seconds', -1), 3) for s in d.get('steps',[])}
    except Exception as exc:
        return {"_error": repr(exc)}
cold,warm=steps(cold_mf),steps(warm_mf)
json.dump({"scenario":"blockMesh-only 600000 cells (300x100x20), steps=blockMesh,checkMesh",
           "note":"checkMesh is intentionally NOT skipped by the cache; only mesh generation is reused",
           "cold_seconds":t1,"warm_seconds":t2,
           "cold_exit":int(rc1),"warm_exit":int(rc2),
           "cache_speedup":round(t1/t2,3) if t2 else None,
           "cold_step_seconds":cold,
           "warm_step_seconds":warm,
           "blockMesh_skipped_in_warm":"blockMesh" not in warm,
           "checkMesh_still_run_in_warm":"checkMesh" in warm},
          open(out,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
print("written:",out)
EOF
