#!/bin/bash
# T-050 改约版 · b15 扩展域 kOmegaSST case 准备（WSL 侧，幂等：DST 已存在即拒绝）
# 依据：用户 03:3x 域标准统一裁定（新结果一律扩展域口径）。
# SRC = T-054 VERIFIED 扩展域 case（只读）；DST = 独立目录；唯一变量 = 湍流模型。
# 已实测（非假定）：SRC 的 wall patch 为 type wall；fvSchemes 已带 div(phi,k)/div(phi,omega) bounded。
set -e
SRC=/home/lenovo2/patient_cfd/t054_b15_oroext/foam_maxh1
DST=/home/lenovo2/t050_b15_komsst_ext
if [ -d "$DST" ]; then echo "REFUSE: $DST already exists"; exit 1; fi
mkdir -p "$DST"
rsync -a --exclude=VTK --exclude=postProcessing --exclude='log.*' --exclude='*.msh' \
  --exclude='0' --exclude='200' --exclude='400' --exclude='600' "$SRC/" "$DST/"
mkdir -p "$DST/0"
cp "$SRC/600/U" "$DST/0/U"
cp "$SRC/600/p" "$DST/0/p"
sed -i 's/location    "600"/location    "0"/' "$DST/0/U" "$DST/0/p"

# 湍流模型：laminar -> RAS kOmegaSST
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

# k：I=5% · U_in≈1.53 m/s（T-054 实测鼻孔均速 L1.511/R1.526）→ k_in = 1.5*(0.0765)^2 ≈ 8.8e-3，取 9.1e-3（同原估）
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
    oropharynx_truncation_outlet { type inletOutlet; inletValue uniform 1e-6; value uniform 1e-6; }
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
    oropharynx_truncation_outlet { type inletOutlet; inletValue uniform 1; value uniform 1; }
}
EOF

# nut：y+ 估算（扩展域重估中）→ Spalding 连续壁面律（缓冲区通用）
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
    oropharynx_truncation_outlet { type calculated; value uniform 0; }
}
EOF

# fvSolution：S-A 已验证组合 + k/omega 同规格求解器与松弛（fvSchemes 零改动：已带 k/omega bounded）
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

echo "== verify: patch names + wall type + schemes =="
grep -E "nostril_L|nostril_R|oropharynx_truncation_outlet|wall" "$DST/constant/polyMesh/boundary" | grep -E "type|nFaces"
grep -c "type            wall;" "$DST/constant/polyMesh/boundary"
grep -E "div\(phi,k\)|div\(phi,omega\)" "$DST/system/fvSchemes"
grep -E "^endTime" "$DST/system/controlDict"
echo "== 0/ fields =="
ls "$DST/0/"
echo "PREPARED: $DST"
