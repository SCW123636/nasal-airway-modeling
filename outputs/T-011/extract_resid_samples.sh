#!/bin/bash
# Residual endpoints & samples for Ux/Uy/Uz/p over the retained 200->600 window.
LOG=/home/lenovo2/t011_p0/snappy/log.simpleFoam
awk '
/^Time = /{t=$3}
/Solving for Ux,/{r=$0; sub(/.*Initial residual = /,"",r); sub(/,.*/,"",r); ux[t]=r}
/Solving for Uy,/{r=$0; sub(/.*Initial residual = /,"",r); sub(/,.*/,"",r); uy[t]=r}
/Solving for Uz,/{r=$0; sub(/.*Initial residual = /,"",r); sub(/,.*/,"",r); uz[t]=r}
/Solving for p,/{r=$0; sub(/.*Initial residual = /,"",r); sub(/,.*/,"",r); if(!(t in p)) p[t]=r}
END{
  split("201 250 300 350 400 450 500 550 600",T," ");
  printf "%-6s %-14s %-14s %-14s %-14s\n","Time","Ux0","Uy0","Uz0","p0(first)";
  for(i=1;i<=9;i++){k=T[i]; printf "%-6s %-14s %-14s %-14s %-14s\n",k,ux[k],uy[k],uz[k],p[k]}
}
' "$LOG"
