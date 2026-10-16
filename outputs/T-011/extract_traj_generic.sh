#!/bin/bash
# Generic residual-trajectory extractor. Usage: bash extract_traj_generic.sh <log_path>
# $1 is expanded by THIS script's own bash (safe; the WSL hazard is only about
# variables passed through the outer Git Bash -> wsl bash -lc layer).
LOG="$1"
[ -f "$LOG" ] || { echo "NO LOG: $LOG"; exit 1; }

echo "=== Ux initial residual: samples ==="
awk '
/^Time = /{t=$3}
/Solving for Ux,/{r=$0; sub(/.*Initial residual = /,"",r); sub(/,.*/,"",r); print t" "r}
' "$LOG" > /tmp/ux_traj.txt
awk 'NR==1||NR%50==0||NR==401{printf "iter=%4d  Time=%-6s Ux0=%s\n", NR, $1, $2}' /tmp/ux_traj.txt | head -15

echo
awk 'NR==1{printf "first: Time=%s Ux0=%s\n",$1,$2}' /tmp/ux_traj.txt
awk 'BEGIN{min=1e9} {if($2+0<min){min=$2+0;mt=$1}} END{printf "min:   Time=%s Ux0=%.6e\n",mt,min}' /tmp/ux_traj.txt
tail -1 /tmp/ux_traj.txt | awk '{printf "final: Time=%s Ux0=%s\n",$1,$2}'
awk 'BEGIN{min=1e9} {if($2+0<min)min=$2+0; last=$2+0} END{printf "final/min - 1 = %+.1f%%\n",(last/min-1)*100}' /tmp/ux_traj.txt

echo
echo "=== residual samples (Ux/Uy/Uz/p-first) ==="
awk '
/^Time = /{t=$3}
/Solving for Ux,/{r=$0; sub(/.*Initial residual = /,"",r); sub(/,.*/,"",r); ux[t]=r}
/Solving for Uy,/{r=$0; sub(/.*Initial residual = /,"",r); sub(/,.*/,"",r); uy[t]=r}
/Solving for Uz,/{r=$0; sub(/.*Initial residual = /,"",r); sub(/,.*/,"",r); uz[t]=r}
/Solving for p,/{r=$0; sub(/.*Initial residual = /,"",r); sub(/,.*/,"",r); if(!(t in p)) p[t]=r}
END{
  split("1 2 100 200 300 400 450 500 550 600",T," ");
  printf "%-6s %-14s %-14s %-14s %-14s\n","Time","Ux0","Uy0","Uz0","p0(first)";
  for(i=1;i<=10;i++){k=T[i]; if(k in ux) printf "%-6s %-14s %-14s %-14s %-14s\n",k,ux[k],uy[k],uz[k],p[k]}
}
' "$LOG"

echo
echo "=== continuity errors at selected times ==="
awk '
/^Time = /{t=$3}
/continuity errors/{print "T="t": "$0}
' "$LOG" | awk 'NR==1||NR==2||NR%100==0{print}' | head -12
