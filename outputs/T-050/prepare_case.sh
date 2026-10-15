#!/bin/bash
# T-050 · b15 maxh1 kOmegaSST case 准备（WSL 侧，幂等：DST 已存在即拒绝）
# 口径与 T-006/T-041 完全一致（固定 50:50 + 出口 p=0），仅改湍流模型与新增 k/omega/nut 场。
set -e
SRC=/home/lenovo2/t042_b15_wssfix
DST=/home/lenovo2/t050_b15_komsst
if [ -d "$DST" ]; then echo "REFUSE: $DST already exists"; exit 1; fi
mkdir -p "$DST"
rsync -a --exclude=VTK --exclude=0 --exclude=200 --exclude=400 --exclude=600 \
  --exclude=postProcessing --exclude='log.*' --exclude='*.msh' "$SRC/" "$DST/"
mkdir -p "$DST/0"
cp "$SRC/600/U" "$DST/0/U"
cp "$SRC/600/p" "$DST/0/p"
sed -i 's/location    "600"/location    "0"/' "$DST/0/U" "$DST/0/p"

cat > "$DST/constant/turbulenceProperties" << 'EOF'
FoamFile
{
 version 2.0;
 format ascii;
 class dictionary;
 object turbulenceProperties;
}
simulationType RAS;
RAS
{
 RASModel kOmegaSST;
 turbulence on;
 printCoeffs on;
}
EOF

# k：I=5% · U_in≈1.56 m/s → k_in = 1.5*(0.078)^2 ≈ 9.1e-3 m^2/s^2
cat > "$DST/0/k" << 'EOF'
FoamFile
{
 version 2.0;
 format ascii;
 class volScalarField;
 location "0";
 object k;
}
dimensions [0 2 -2 0 0 0 0];
internalField uniform 1e-6;
boundaryField
{
    nostril_L { type fixedValue; value uniform 9.1e-3; }
    nostril_R { type fixedValue; value uniform 9.1e-3; }
    wall { type kqRWallFunction; value uniform 1e-10; }
    nasopharynx_outlet { type inletOutlet; inletValue uniform 1e-6; value uniform 1e-6; }
}
EOF

# omega：L≈0.07·D_h≈8e-4 m → omega_in = sqrt(k)/(0.09^0.25·L) ≈ 218 1/s
cat > "$DST/0/omega" << 'EOF'
FoamFile
{
 version 2.0;
 format ascii;
 class volScalarField;
 location "0";
 object omega;
}
dimensions [0 0 -1 0 0 0 0];
internalField uniform 1;
boundaryField
{
    nostril_L { type fixedValue; value uniform 218; }
    nostril_R { type fixedValue; value uniform 218; }
    wall { type omegaWallFunction; value uniform 1; }
    nasopharynx_outlet { type inletOutlet; inletValue uniform 1; value uniform 1; }
}
EOF

# nut：y+ 中位≈6.5（缓冲区）→ Spalding 连续壁面律
cat > "$DST/0/nut" << 'EOF'
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
    wall { type nutUSpaldingWallFunction; value uniform 0; }
    nasopharynx_outlet { type calculated; value uniform 0; }
}
EOF

# fvSolution：沿用 S-A 已验证组合，补 k/omega 求解器与松弛
cat > "$DST/system/fvSolution" << 'EOF'
FoamFile
{
 version 2.0;
 format ascii;
 class dictionary;
 object fvSolution;
}

solvers
{
 p { solver GAMG; tolerance 1e-12; relTol 0.01; smoother GaussSeidel; }
 U { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-12; relTol 0.01; }
 k { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-12; relTol 0.01; }
 omega { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-12; relTol 0.01; }
}
SIMPLE
{
 nNonOrthogonalCorrectors 2;
 consistent yes;
 residualControl { p 1e-10; U 1e-8; k 1e-6; omega 1e-6; }
}
relaxationFactors { equations { U 0.7; k 0.7; omega 0.7; } fields { p 0.3; } }
EOF

echo "PREPARED: $DST"
ls "$DST/0/"
