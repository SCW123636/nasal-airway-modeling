#!/bin/bash
# Ux initial-residual trajectory: locate the bottom-out time and any rebound.
# Literal paths only (WSL eats variables from the outer shell).
awk '
/^Time = /{t=$3}
/Solving for Ux,/{r=$0; sub(/.*Initial residual = /,"",r); sub(/,.*/,"",r); print t" "r}
' /home/lenovo2/t011_p0/snappy/log.simpleFoam > /tmp/ux_traj.txt

echo "=== Ux initial residual: samples ==="
awk 'NR==1||NR==50||NR==100||NR==200||NR==300||NR==400||NR==401{printf "iter=%4d  Ux0=%s\n", NR, $2}' /tmp/ux_traj.txt

echo
echo "=== bottom-out ==="
awk 'BEGIN{min=1e9} {if($2+0<min){min=$2+0; mint=$1}} END{printf "min Ux0 = %.6e at Time=%s (iter %d of %d)\n", min, mint, 0, NR}' /tmp/ux_traj.txt
awk 'BEGIN{min=1e9} {if($2+0<min){min=$2+0; mi=NR}} END{print "min at row "mi" of "NR}' /tmp/ux_traj.txt
tail -1 /tmp/ux_traj.txt | awk '{printf "final Ux0 = %s at Time=%s\n",$2,$1}'
awk 'BEGIN{min=1e9} {if($2+0<min)min=$2+0} END{}' /tmp/ux_traj.txt
awk 'NR==1{print "first Ux0 (Time="$1") = "$2}' /tmp/ux_traj.txt

echo
echo "=== rebound fraction (min -> final) ==="
awk 'BEGIN{min=1e9} {if($2+0<min)min=$2+0; last=$2+0} END{printf "final/min - 1 = %+.1f%%\n",(last/min-1)*100}' /tmp/ux_traj.txt

echo
echo "=== window of values around the minimum ==="
awk 'BEGIN{min=1e9} {if($2+0<min){min=$2+0;mi=NR}} {a[NR]=$0} END{for(i=mi-3;i<=mi+5;i++) if(i>=1&&i<=NR) print a[i]}' /tmp/ux_traj.txt
