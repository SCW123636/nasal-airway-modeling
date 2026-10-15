#!/bin/bash
# Patient passive-scalar run hit sigFpe in symGaussSeidelSmoother. Same mesh that
# broke k-omega wall functions (466 det<0.001 slivers). Try a more robust combo:
# GAMG solver + first-order upwind convection + looser tolerance.
set -e
D=/home/lenovo2/t043_b15_temp
sed -i 's|^ T { solver smoothSolver.*$| T { solver GAMG; tolerance 1e-09; relTol 0.001; smoother GaussSeidel; }|' "$D/system/fvSolution"
sed -i 's|    div(phi,T)      bounded Gauss limitedLinear 1;|    div(phi,T)      bounded Gauss upwind;|' "$D/system/fvSchemes"
echo "=== fvSolution T ==="
grep -n "T {" "$D/system/fvSolution"
echo "=== fvSchemes div(phi,T) ==="
grep -n "div(phi,T)" "$D/system/fvSchemes"
