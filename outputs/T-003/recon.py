import io
from pathlib import Path

BASE = Path("/mnt/d/项目/鼻腔建模")
RUN = BASE / "work" / "07_cfd_pipeline" / "solver" / "run_openfoam_case.py"
TEST = BASE / "work" / "lib" / "test_run_openfoam_case.py"
OUT = BASE / "outputs" / "T-003"

N1 = r'''sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_cache

# --- contract gate (T-003 R10) ------------------------------------------------
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


SCRIPT_VERSION = "1.2.0"'''

O1 = r'''sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_cache

SCRIPT_VERSION = "1.2.0"'''

N2 = r'''    parser.add_argument('--dry-run', action='store_true',
                        help='print the planned command sequence and exit without executing or writing')
    parser.add_argument('--config', default=None,
                        help='path to a nasal_cfd_config/v1 json; enforces the contract gate '
                             '(refuses to run unless execution_allowed, override with --force-unsanctioned)')
    parser.add_argument('--force-unsanctioned', action='store_true',
                        help='explicitly run an execution_allowed=false config anyway; '
                             'recorded in run_manifest.contract.forced for audit (never lifts engineering_acceptance)')
    args = parser.parse_args(argv)'''

O2 = r'''    parser.add_argument('--dry-run', action='store_true',
                        help='print the planned command sequence and exit without executing or writing')
    args = parser.parse_args(argv)'''

N3 = r'''    args = parser.parse_args(argv)
    if args.env_check:
        return env_check(build_environment())
    # --- contract gate (T-003 R10): evaluate before any step executes ---------
    try:
        contract = evaluate_contract(args)
    except ContractRefusal as ref:
        print("run_openfoam_case error: refusing to run an unsanctioned configuration "
              "(pass --force-unsanctioned to override explicitly, recorded for audit):",
              file=sys.stderr)
        for reason in ref.reasons:
            print("  - " + str(reason), file=sys.stderr)
        return 3
    if not args.case:'''

O3 = r'''    args = parser.parse_args(argv)
    if args.env_check:
        return env_check(build_environment())
    if not args.case:'''

N4 = r'''                    "mesh_skipped": skipped_mesh,
                    "archived_before_run": archived,
                    "contract": contract}
    run_manifest['engineering_acceptance'] = False'''

O4 = r'''                    "mesh_skipped": skipped_mesh,
                    "archived_before_run": archived}
    run_manifest['engineering_acceptance'] = False'''


def reverse(text, pairs):
    for new, old in pairs:
        cnt = text.count(new)
        if cnt != 1:
            raise SystemExit("EXPECTED 1 occurrence, found %d for:\n%.120s" % (cnt, new))
        text = text.replace(new, old)
    return text


run_before = reverse(RUN.read_text(encoding="utf-8"), [(N1, O1), (N2, O2), (N3, O3), (N4, O4)])
(RUN.parent / "before_run_openfoam_case.py").write_text(run_before, encoding="utf-8")

cur = TEST.read_text(encoding="utf-8")
NB_MARK_START = "class ContractGateTests(unittest.TestCase):"
NB_MARK_END = "if __name__=='__main__':\n    unittest.main()"
idx_s = cur.index(NB_MARK_START)
idx_e = cur.index(NB_MARK_END)
test_before = cur[:idx_s] + "\n" + NB_MARK_END
(TEST.parent / "before_test_run_openfoam_case.py").write_text(test_before, encoding="utf-8")

print("reconstruction OK")
print("run_before len", len(run_before))
print("test_before len", len(test_before))
