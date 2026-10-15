#!/bin/bash
# Repair divSchemes broken by the earlier in-place replace: div(phi,U) lost its
# scheme value and div(phi,T) swallowed two schemes on one line.
set -e
P=/home/lenovo2/t043_b15_temp/system/fvSchemes
python3 - <<'PYEOF'
p = "/home/lenovo2/t043_b15_temp/system/fvSchemes"
lines = open(p).read().splitlines()
out = []
for ln in lines:
    s = ln.strip()
    if s == "div(phi,U)":
        continue
    if s.startswith("div(phi,T)") and "linearUpwind" in s:
        out.append("    div(phi,U)      bounded Gauss linearUpwind grad(U);")
        out.append("    div(phi,T)      bounded Gauss limitedLinear 1;")
        continue
    out.append(ln)
open(p, "w").write("\n".join(out) + "\n")
print("repaired")
PYEOF
sed -n '/^divSchemes/,/^}/p' "$P"
