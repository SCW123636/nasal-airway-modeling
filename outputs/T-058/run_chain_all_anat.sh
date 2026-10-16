#!/bin/bash
# T-058 anatomical-cut 3-case serial driver. All variables live in this file;
# nothing crosses the wsl.exe boundary (the eaten-$ trap, twice).
cd /home/lenovo2/t058_chain_anat || exit 1
for C in b15 b01 b02; do
  echo "########## $C start $(date +%H:%M:%S) ##########"
  mkdir -p "/home/lenovo2/t058_chain_anat/$C"
  bash "/home/lenovo2/t058_chain_anat/chain_case_anat.sh" "$C" \
       > "/home/lenovo2/t058_chain_anat/$C/chain.log" 2>&1
  echo "$C exit=$?"
  tail -3 "/home/lenovo2/t058_chain_anat/$C/chain.log"
done
echo "ALL-DONE $(date +%H:%M:%S)"
