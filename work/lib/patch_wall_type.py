"""Patch an OpenFOAM polyMesh boundary patch's TYPE in constant/polyMesh/boundary.

WHY THIS EXISTS (2026-10-16, T-042)
-----------------------------------
gmshToFoam / surface_to_case.py builds EVERY patch as `type patch`.  The
wallShearStress function object only recognises `type wall` patches
(wallPolyPatch); on a `type patch` wall it silently writes ZERO for every
face with no error message.  Verified twice on b15_maxh1:

  * original case (type patch)      -> 600/wallShearStress wall block all (0 0 0)
                                       VTK wall.vtp wallShearStress all "0 0 0"
                                       extractor reported wall_shear_force_n = 0.0 N
  * same case, wall -> type wall    -> 86822 non-zero vectors
                                       wall_shear_force_n = 0.0011019165435884187 N
                                       (delta_p bit-identical: the fix touches
                                       only the patch's metadata, not the mesh)

The same silent-zero trap awaits T-043 (wall heat flux needs type wall too).

WHAT THIS TOOL DOES
-------------------
Rewrites ONE patch block in constant/polyMesh/boundary:
  * `type            patch;`  ->  `type            wall;`   (configurable)
  * inserts `inGroups        1(wall);` right after the type line
    (aligns with the verified Windcatcher reference case; inGroups is what
    patch-name-based tooling matches on)
  * drops a `physicalType    patch;` line inside the block if present
    (the two verified reference cases carry type wall + inGroups, no
    physicalType)
  * nFaces / startFace / every other patch block are left BYTE-IDENTICAL

Idempotent: if the block already has the target type and group and no
physicalType, nothing is written (reported as no-op).

Usage (WSL, standard library only):
    python3 patch_wall_type.py --case /home/lenovo2/some_case --patch wall
    python3 patch_wall_type.py --case ... --patch wall --type wall --group wall

Exit codes: 0 = patched or already-correct, 2 = error (file/patch not found).
"""
import argparse
import hashlib
import sys
from pathlib import Path

INDENT = "    "          # patch-name lines in a FoamFile boundary dict
FIELD_INDENT = "        "  # fields inside a patch block


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_block_lines(block, target_type, target_group):
    """Return the rewritten lines of one patch block.

    The type line is rewritten and a fresh inGroups line is inserted right
    after it; any pre-existing inGroups / physicalType lines inside the block
    are dropped (they are replaced by the fresh, canonical pair).  Every other
    line -- including nFaces / startFace -- is copied byte-identically.
    """
    out = []
    dropped_physical = False
    for line in block:
        stripped = line.strip()
        if stripped.startswith("type"):
            out.append(FIELD_INDENT + "type            %s;\n" % target_type)
            if target_group:
                out.append(FIELD_INDENT + "inGroups        1(%s);\n" % target_group)
            continue
        if stripped.startswith("physicalType"):
            dropped_physical = True
            continue
        if stripped.startswith("inGroups"):
            continue  # replaced by the canonical pair inserted after the type line
        out.append(line.rstrip("\n") + "\n")
    if not any(l.strip().startswith("type") for l in block):
        # patch block without a type line: insert the canonical pair after "{"
        fixed = []
        for i, line in enumerate(out):
            fixed.append(line)
            if i == 0 and line.strip() == "{":
                fixed.append(FIELD_INDENT + "type            %s;\n" % target_type)
                if target_group:
                    fixed.append(FIELD_INDENT + "inGroups        1(%s);\n" % target_group)
        out = fixed
    return out, dropped_physical


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", required=True, help="OpenFOAM case directory")
    ap.add_argument("--patch", default="wall", help="patch name to patch (default wall)")
    ap.add_argument("--type", default="wall", help="target patch type (default wall)")
    ap.add_argument("--group", default="wall", help="inGroup to ensure (default wall; '' to skip)")
    args = ap.parse_args(argv)

    boundary = Path(args.case) / "constant" / "polyMesh" / "boundary"
    if not boundary.is_file():
        print("patch_wall_type error: not found: %s" % boundary, file=sys.stderr)
        return 2

    lines = boundary.read_text(encoding="utf-8").splitlines(keepends=True)
    before_md5 = sha256(boundary)

    out = []
    i = 0
    n = len(lines)
    state = "outside"   # outside | in_patch
    current = None
    block = []
    patched = False
    already = False
    while i < n:
        line = lines[i]
        if state == "outside":
            name = line.rstrip("\n")
            if line.startswith(INDENT) and name.strip() == args.patch and not name.strip().endswith(";"):
                state = "in_patch"
                current = args.patch
                block = [line]
                i += 1
                continue
            out.append(line)
            i += 1
            continue
        # in_patch: collect until the closing "    }"
        block.append(line)
        if line.startswith(INDENT + "}"):
            new_block, dropped = patch_block_lines(block, args.type, args.group)
            text = "".join(new_block)
            if text == "".join(block):
                already = True
                print("patch_wall_type: patch '%s' already type %s with inGroups 1(%s); no-op"
                      % (args.patch, args.type, args.group))
            else:
                patched = True
                print("patch_wall_type: patch '%s' rewritten (physicalType dropped: %s)"
                      % (args.patch, dropped))
                print("--- before ---")
                print("".join(block))
                print("--- after ---")
                print(text)
            out.extend(new_block)
            state = "outside"
            current = None
            block = []
            i += 1
            continue
        i += 1

    if state == "in_patch":
        print("patch_wall_type error: unterminated block for patch '%s'" % args.patch,
              file=sys.stderr)
        return 2
    if not patched and not already:
        print("patch_wall_type error: patch '%s' not found in %s" % (args.patch, boundary),
              file=sys.stderr)
        print("patch names present:", file=sys.stderr)
        for line in lines:
            if line.startswith(INDENT) and line.strip() == line.strip().rstrip(";") \
                    and not line.strip().endswith(";") and line.strip() not in ("{", "}"):
                print("  %r" % line.strip(), file=sys.stderr)
        return 2

    if patched:
        boundary.write_text("".join(out), encoding="utf-8")
        after_md5 = sha256(boundary)
        print("boundary md5 before: %s" % before_md5)
        print("boundary md5 after:  %s" % after_md5)
        if before_md5 == after_md5:
            print("patch_wall_type error: file unchanged after write", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
