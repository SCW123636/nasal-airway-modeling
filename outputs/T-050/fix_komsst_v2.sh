#!/bin/bash
# T-050 v2 fix: omega blow-up at step 1 suspected from wall-function 1/y^2 on
# near-wall degenerate cells. Fix attempt (config-only, geometry untouched):
#   1. nut wall: nutUSpaldingWallFunction -> nutkWallFunction (no iterative y+ solve)
#   2. k/omega internalField raised toward inlet level (less extreme initial gradient)
#   3. wipe any polluted time dirs / postProcessing, restart from clean 0/
# Runs INSIDE WSL. No shell variables crossing the wsl.exe boundary.
set -e
cd /home/lenovo2/t050_b15_komsst_ext

echo "== wipe polluted state =="
rm -rf postProcessing
find . -maxdepth 1 -regex './[0-9]+' -not -name '0' -exec rm -rf {} + 2>/dev/null || true
ls -d ./0 ./constant ./system

echo "== write 0/k =="
cat > 0/k <<'EOF'
FoamFile
{
 version 2.0;
 format ascii;
 class volScalarField;
 location "0";
 object k;
}
dimensions [0 2 -2 0 0 0 0];
internalField uniform 1e-3;
boundaryField
{
    nostril_L { type fixedValue; value uniform 9.1e-3; }
    nostril_R { type fixedValue; value uniform 9.1e-3; }
    wall { type kqRWallFunction; value uniform 1e-3; }
    oropharynx_truncation_outlet { type inletOutlet; inletValue uniform 1e-3; value uniform 1e-3; }
}
EOF

echo "== write 0/omega =="
cat > 0/omega <<'EOF'
FoamFile
{
 version 2.0;
 format ascii;
 class volScalarField;
 location "0";
 object omega;
}
dimensions [0 0 -1 0 0 0 0];
internalField uniform 100;
boundaryField
{
    nostril_L { type fixedValue; value uniform 218; }
    nostril_R { type fixedValue; value uniform 218; }
    wall { type omegaWallFunction; value uniform 100; }
    oropharynx_truncation_outlet { type inletOutlet; inletValue uniform 100; value uniform 100; }
}
EOF

echo "== write 0/nut (nutkWallFunction) =="
cat > 0/nut <<'EOF'
FoamFile
{
 version 2.0;
 format ascii;
 class volScalarField;
 location "0";
 object nut;
}
dimensions [0 2 -1 0 0 0 0];
internalField uniform 0;
boundaryField
{
    nostril_L { type calculated; value uniform 0; }
    nostril_R { type calculated; value uniform 0; }
    wall { type nutkWallFunction; value uniform 0; }
    oropharynx_truncation_outlet { type calculated; value uniform 0; }
}
EOF

echo "== sanity =="
grep -h 'internalField' 0/k 0/omega 0/nut
grep -h 'type  *nut' 0/nut
echo "FIX-V2-DONE"
