#!/bin/bash
# Extract residual trajectory + continuity-error samples from the A.1 snappy solve log.
# Literal paths only: WSL eats shell variables passed through the outer bash (known hazard).
LOG=/home/lenovo2/t011_p0/snappy/log.simpleFoam

echo "=== continuity errors at selected times ==="
awk '
/^Time = /{t=$3}
/Eqns|continuity errors|sum local/{ }
/continuity errors/{print "T="t": "$0}
' /home/lenovo2/t011_p0/snappy/log.simpleFoam | awk 'NR==1||NR==2||NR==5||NR==10||NR==20{print}' 

echo
echo "=== first 3 time blocks (Time=1..3) ==="
awk '/^Time = /{n++} n<=3{print}' /home/lenovo2/t011_p0/snappy/log.simpleFoam | grep -E "^Time = |continuity errors|GAMG|DILUPBiCG|smoothSolver" | head -40

echo
echo "=== convergence marker check ==="
grep -n "SIMPLE solution converged" /home/lenovo2/t011_p0/snappy/log.simpleFoam || echo "(no SIMPLE solution converged)"

echo
echo "=== last written time block (Time=600) residuals ==="
awk '/^Time = 600$/{f=1} f{print}' /home/lenovo2/t011_p0/snappy/log.simpleFoam | grep -E "Solving for|Initial residual|Final residual|No Iterations|continuity" | head -20
