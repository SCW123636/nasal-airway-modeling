"""T-003 R10 compatibility proof.

Goal: demonstrate that when --config is NOT supplied, the executor behaves
byte-for-byte identically to a variant of the *same* file with only the
contract-gate (T-003 R10) insertions removed.

We build a "no-gate" twin of run_openfoam_case.py by deleting exactly the four
blocks T-003 added (contract import + ContractRefusal + evaluate_contract;
the --config / --force-unsanctioned argparse args; the gate try/except in main;
the "contract": contract manifest field) and reverting SCRIPT_VERSION to 1.1.0.
Both modules are then driven with identical mocks and the same argv (no
--config). The executed command sequence and the run_manifest (with the
behaviourally-irrelevant `contract` and `script` keys removed) must match.
"""
import importlib.util
import io
import json
import sys
import tempfile
import contextlib
from pathlib import Path
from unittest import mock

SRC = Path(__file__).resolve().parents[2] / "work" / "07_cfd_pipeline" / "solver" / "run_openfoam_case.py"
text = SRC.read_text(encoding="utf-8")

# --- the four T-003-inserted blocks (exact substrings) -----------------------
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

assert block_a in text, "block_a not found (file may have drifted)"
assert block_b in text, "block_b not found"
assert block_c in text, "block_c not found"
assert block_d in text, "block_d not found"

nogate = text
nogate = nogate.replace(block_a, 'SCRIPT_VERSION = "1.1.0"\n', 1)
nogate = nogate.replace(block_b, "", 1)
nogate = nogate.replace(block_c, "", 1)
nogate = nogate.replace(block_d, "}", 1)
# the gate removal leaves a dangling `contract` variable? No: block_d removed the
# only use; evaluate_contract (block_a) and the gate (block_c) are gone, so
# `contract` is never referenced. Good.


def load_module(source_text, name):
    spec = importlib.util.spec_from_file_location(name, SRC)
    mod = importlib.util.module_from_spec(spec)
    exec(compile(source_text, SRC, "exec"), mod.__dict__)
    return mod


current = load_module(text, "exec_current")
nogate_mod = load_module(nogate, "exec_nogate")


def run(mod):
    executed = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with mock.patch.object(mod, "check_case_complete"), \
             mock.patch.object(mod, "is_sst", return_value=False), \
             mock.patch.object(mod, "mesh_quality", return_value={"passed": True}), \
             mock.patch.object(mod, "execute", side_effect=lambda cmd, case, env, log:
                               (executed.append(cmd) or {"command": cmd, "exit_code": 0,
                                                         "elapsed_seconds": 0.0, "log": str(case / log)})):
            rc = mod.main(["--case", str(root), "--steps", "simpleFoam,foamToVTK"])
        manifest = json.loads((root / "run_manifest.json").read_text())
    return rc, executed, manifest


def normalize(manifest, placeholder="/TMP"):
    m = dict(manifest)
    m["case"] = placeholder
    if isinstance(m.get("steps"), list):
        for s in m["steps"]:
            if isinstance(s, dict) and isinstance(s.get("log"), str):
                s["log"] = placeholder + "/log." + s["command"][0]
    return m


rc_c, exec_c, man_c = run(current)
rc_n, exec_n, man_n = run(nogate_mod)

# Strip behaviourally-irrelevant keys and normalize the per-run temp path.
strip = {"contract", "script", "started_at", "finished_at"}
man_c_cmp = normalize({k: v for k, v in man_c.items() if k not in strip})
man_n_cmp = normalize({k: v for k, v in man_n.items() if k not in strip})

print("=== T-003 R10 compatibility proof (no --config) ===")
print("current  rc=%s  executed_commands=%s" % (rc_c, exec_c))
print("nogate   rc=%s  executed_commands=%s" % (rc_n, exec_n))
print("command sequences identical :", exec_c == exec_n)
print("exit codes identical        :", rc_c == rc_n)
print("manifests identical (minus contract/script/timestamps):", man_c_cmp == man_n_cmp)
print("current manifest contract field:", man_c.get("contract"))

if man_c_cmp != man_n_cmp:
    kc, kn = set(man_c_cmp), set(man_n_cmp)
    print("  manifest keys only in current:", sorted(kc - kn))
    print("  manifest keys only in nogate :", sorted(kn - kc))
    for k in sorted(kc & kn):
        if man_c_cmp[k] != man_n_cmp[k]:
            print("  DIFF key %r: %r VS %r" % (k, man_c_cmp[k], man_n_cmp[k]))

ok = (rc_c == rc_n == 0) and (exec_c == exec_n) and (man_c_cmp == man_n_cmp)
print("RESULT:", "PASS - behaviour byte-identical without --config" if ok else "FAIL")
sys.exit(0 if ok else 1)
