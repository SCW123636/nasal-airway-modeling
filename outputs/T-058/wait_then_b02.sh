#!/bin/bash
# T-058 anatomical-cut MEMORY-AWARE ramp.
#
# Why this exists: netgen peaks at ~5.8 GB RSS and the WSL box has 7.8 GB total,
# while a solve only needs ~0.7 GB.  Two overlapping meshers OOM-kill everything
# on the box (including innocent solvers), so the rule is:
#
#     at most ONE mesher at a time, and at most one solver alongside it.
#
# Situation: b15 is already solving (started earlier by the serial driver, which
# was SIGSTOPped).  This watchdog waits until b15's chain finishes - by then b01
# is long past its mesher and only solving - and then runs b02's full chain.
# At that point b02's mesher is the only heavy resident (b01 solve 0.7 GB).
#
# Variables live inside this file only (never cross the wsl.exe boundary).
cd /home/lenovo2/t058_chain_anat || exit 1
while ! grep -q 'CHAIN-DONE b15' /home/lenovo2/t058_chain_anat/b15/chain.log 2>/dev/null; do
  sleep 20
done
echo "b15 finished at $(date +%H:%M:%S); b01 mesher is long past - starting b02"
bash /home/lenovo2/t058_chain_anat/chain_case_anat.sh b02 \
     > /home/lenovo2/t058_chain_anat/b02/chain.log 2>&1
echo "b02 exit=$? $(date +%H:%M:%S)"
echo "RAMP-DONE $(date +%H:%M:%S)"
