"""Generate outputs/T-003/我的hunk.diff: the diff of ONLY T-003 R10's additions
(contract gate in run_openfoam_case.py + ContractGateTests in test_run_openfoam_case.py),
isolated from the parallel session's engineering-bonus changes.

"old" side for each file = current working tree with T-003's insertions removed
(== the parallel-session baseline). "new" side = current working tree.
diff(old, new) therefore contains exactly T-003's additions across both files.
"""
import difflib
import os
import py_compile
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[2] / "work"

# ---------------------------------------------------------------------------
# run_openfoam_case.py : remove the four T-003-inserted blocks
# ---------------------------------------------------------------------------
SRC_MAIN = BASE / "07_cfd_pipeline" / "solver" / "run_openfoam_case.py"
main = SRC_MAIN.read_text(encoding="utf-8")

block_a = '''# --- contract gate (T-003 R10) ------------------------------------------------
# The contract module lives in work/lib; on WSL `Path(__file__).resolve().
# parents[2] / "lib"` resolves there. Imported up front so a missing module
# fails loudly and clearly instead of surfacing as a bare ImportError traceback.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
try:
    import cfd_contract
except ImportError as exc:
    _lib_dir = Path(__file__).resolve().parents[2] / "lib"
    print("run_openfoam_case error: cannot import contract module 'cfd_contract' "
          "from %s: %s" % (_lib_dir, exc), file=sys.stderr)
    raise SystemExit(2)


class ContractRefusal(Exception):
    """Raised when a --config is supplied but is not execution-allowed."""

    def __init__(self, reasons):
        super().__init__("unsanctioned configuration")
        self.reasons = list(reasons)


def evaluate_contract(args):
    """Load + validate the optional --config and return run_manifest['contract'].

    Returns a dict with ``checked`` set False when no --config is given (so the
    script keeps running exactly as before). Raises ``ContractRefusal`` -- before
    any solver step runs -- when ``execution_allowed`` is False and
    --force-unsanctioned was not supplied. The refusal message names the concrete
    blocking reasons (they live in the contract ``warnings`` for our 8 configs).
    """
    if not args.config:
        return {"config_id": None, "checked": False}
    path = Path(args.config)
    if not path.is_file():
        raise ContractRefusal(["--config file not found: %s" % path])
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractRefusal(["--config is not readable/valid JSON (%s): %s" % (path, exc)])
    report = cfd_contract.validate_config(cfg)
    contract = {
        "config_id": cfg.get("config_id"),
        "execution_allowed": bool(report["execution_allowed"]),
        "errors": report["errors"],
        "warnings": report["warnings"],
        "forced": bool(args.force_unsanctioned),
        "checked": True,
    }
    if not report["execution_allowed"] and not args.force_unsanctioned:
        # Concrete blocking reasons: errors first, then readiness warnings
        # (e.g. "solver adapter has not been implemented and verified ...").
        raise ContractRefusal(list(report["errors"]) + list(report["warnings"]))
    return contract


SCRIPT_VERSION = "1.2.0"
'''

block_b = '''    parser.add_argument('--config', default=None,
                        help='path to a nasal_cfd_config/v1 json; enforces the contract gate '
                             '(refuses to run unless execution_allowed, override with --force-unsanctioned)')
    parser.add_argument('--force-unsanctioned', action='store_true',
                        help='explicitly run an execution_allowed=false config anyway; '
                             'recorded in run_manifest.contract.forced for audit (never lifts engineering_acceptance)')
'''

block_c = '''    # --- contract gate (T-003 R10): evaluate before any step executes ---------
    try:
        contract = evaluate_contract(args)
    except ContractRefusal as ref:
        print("run_openfoam_case error: refusing to run an unsanctioned configuration "
              "(pass --force-unsanctioned to override explicitly, recorded for audit):",
              file=sys.stderr)
        for reason in ref.reasons:
            print("  - " + str(reason), file=sys.stderr)
        return 3
'''

block_d = '''                    "contract": contract}'''

main_old = main
main_old = main_old.replace(block_a, 'SCRIPT_VERSION = "1.1.0"\n', 1)
main_old = main_old.replace(block_b, "", 1)
main_old = main_old.replace(block_c, "", 1)
main_old = main_old.replace(block_d, "}", 1)

# ---------------------------------------------------------------------------
# test_run_openfoam_case.py : remove ContractGateTests + its imports
# ---------------------------------------------------------------------------
SRC_TEST = BASE / "lib" / "test_run_openfoam_case.py"
test = SRC_TEST.read_text(encoding="utf-8")

test_old = test
# imports exclusive to ContractGateTests
test_old = test_old.replace("import contextlib\n", "", 1)
test_old = test_old.replace("import io\n", "", 1)
# the whole ContractGateTests class (with surrounding blank lines)
start = test_old.index("\n\nclass ContractGateTests(unittest.TestCase):")
end = test_old.index("\n\n\nif __name__=='__main__':")
test_old = test_old[:start] + "\n\nif __name__=='__main__':" + test_old[end + len("\n\n\nif __name__=='__main__':"):]

# ---------------------------------------------------------------------------
# sanity: both "old" sides must still be valid Python
# ---------------------------------------------------------------------------
for label, src in (("main_old", main_old), ("test_old", test_old)):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(src)
        tmp = f.name
    try:
        py_compile.compile(tmp, doraise=True)
    finally:
        os.unlink(tmp)

# ---------------------------------------------------------------------------
# emit unified diff
# ---------------------------------------------------------------------------
rel_main = "work/07_cfd_pipeline/solver/run_openfoam_case.py"
rel_test = "work/lib/test_run_openfoam_case.py"
parts = []
parts.append("diff --git a/%s b/%s" % (rel_main, rel_main))
parts.append("--- a/%s" % rel_main)
parts.append("+++ b/%s" % rel_main)
parts += difflib.unified_diff(
    main_old.splitlines(keepends=True), main.splitlines(keepends=True),
    fromfiledate="(parallel-only baseline)", tofiledate="(with T-003 R10 contract gate)")
parts.append("diff --git a/%s b/%s" % (rel_test, rel_test))
parts.append("--- a/%s" % rel_test)
parts.append("+++ b/%s" % rel_test)
parts += difflib.unified_diff(
    test_old.splitlines(keepends=True), test.splitlines(keepends=True),
    fromfiledate="(parallel-only baseline)", tofiledate="(with T-003 R10 ContractGateTests)")

out = "".join(parts)
dest = Path(__file__).resolve().parent / "我的hunk.diff"
dest.write_text(out, encoding="utf-8")
added = sum(1 for ln in out.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
removed = sum(1 for ln in out.splitlines() if ln.startswith("-") and not ln.startswith("---"))
print("wrote %s  (+%d / -%d lines)" % (dest, added, removed))
