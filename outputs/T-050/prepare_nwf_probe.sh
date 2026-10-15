#!/bin/bash
# T-050 root-cause probe: does omega still blow up WITHOUT wall functions?
# If it runs stable -> root cause = wall function (omega ~ 6*nu/(beta*y^2)) amplified by
# near-wall degenerate cells (T-054 mesh: 466 det<0.001 cells).
# If it still blows up -> root cause is k/omega transport on this mesh itself.
# Config-only change on a COPY (source case untouched). Runs INSIDE WSL.
set -e
SRC=/home/lenovo2/t050_b15_komsst_ext
DST=/home/lenovo2/t050_komsst_nwf_probe

rm -rf $DST
mkdir -p $DST
cp -r $SRC/constant $DST/constant
cp -r $SRC/system $DST/system
mkdir -p $DST/0
cp $SRC/0/U $SRC/0/p $DST/0/

cat > $DST/0/k <<'EOF'
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
    wall { type zeroGradient; }
    oropharynx_truncation_outlet { type inletOutlet; inletValue uniform 1e-3; value uniform 1e-3; }
}
EOF

cat > $DST/0/omega <<'EOF'
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
    wall { type zeroGradient; }
    oropharynx_truncation_outlet { type inletOutlet; inletValue uniform 100; value uniform 100; }
}
EOF

cat > $DST/0/nut <<'EOF'
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
    wall { type fixedValue; value uniform 0; }
    oropharynx_truncation_outlet { type calculated; value uniform 0; }
}
EOF

echo "PROBE-CASE-READY $DST"
ls $DST/0
