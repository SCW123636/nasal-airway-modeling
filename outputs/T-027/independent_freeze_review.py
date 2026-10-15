"""Freeze fingerprint/AST/identity checks using synthetic inputs only."""
from __future__ import annotations
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"):
    os.environ[key] = "1"
import numpy as np
import SimpleITK as sitk
sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(1)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--commit", required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    repo = Path(__file__).resolve().parents[2]
    args.out.mkdir(parents=True, exist_ok=False)
    checks = []

    def check(name, actual, expected):
        checks.append({"name": name, "actual": actual, "expected": expected, "pass": actual == expected})

    commit = subprocess.check_output(["git", "rev-parse", args.commit], cwd=repo, text=True).strip()
    prototype = repo / "outputs/T-026/prototype/upper_airway_candidate.py"
    old_snapshot = repo / "outputs/T-026/runs/20261015_04_full/prototype_source_snapshot.py"
    author_scope = ["outputs/T-026", "knowledge/结论卡/20261015-T-026-鼻咽扩展入口.md"]
    changed = subprocess.run(["git", "diff", "--exit-code", commit, "--", *author_scope], cwd=repo, capture_output=True, text=True)
    check("all_tracked_author_artifacts_match_freeze_commit", changed.returncode, 0)
    key_paths = ["outputs/T-026/prototype/upper_airway_candidate.py", "outputs/T-026/prototype/compare_source_series.py",
                 "outputs/T-026/执行入口.md", "outputs/T-026/交付总报告.md", "outputs/T-026/runs/20261015_06_scope_correction/用户更正.md"]
    identities = {}
    for rel in key_paths:
        actual_bytes = (repo / rel).read_bytes()
        frozen_bytes = subprocess.check_output(["git", "show", commit + ":" + rel], cwd=repo)
        actual_hash, frozen_hash = hashlib.sha256(actual_bytes).hexdigest(), hashlib.sha256(frozen_bytes).hexdigest()
        identities[rel] = actual_hash
        check("exact_frozen_bytes:" + rel, actual_hash, frozen_hash)
    old_tree = ast.parse(old_snapshot.read_text(encoding="utf-8"))
    new_tree = ast.parse(prototype.read_text(encoding="utf-8"))
    old_functions = {node.name: ast.dump(node, include_attributes=False) for node in old_tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    new_functions = {node.name: ast.dump(node, include_attributes=False) for node in new_tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    unchanged = ("build_candidate", "require_arrays", "same_grid", "index_to_lps", "ct_extent", "mask_extent", "write_nifti_and_reread", "read_case")
    for name in unchanged:
        check("core_AST_unchanged_since_real_run04:" + name, new_functions[name], old_functions[name])
    spec = importlib.util.spec_from_file_location("frozen_t026_review", prototype)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    check("current_limits_symptom_mapping_unknown", "symptom_patient_mapping_unknown" in module.LIMITS, True)
    check("current_limits_no_outdated_B_assignment", "patient_B_mapping_unknown" in module.LIMITS, False)
    ct_array = np.full((3, 4, 5), 0, dtype=np.int16)
    locations = {"nasal_cavity_left": (1, 1, 0), "nasal_cavity_right": (1, 1, 1), "nasopharynx": (1, 1, 2), "oropharynx": (0, 1, 2)}
    ct = sitk.GetImageFromArray(ct_array)
    ims = {}
    for name, point in locations.items():
        ct_array[point] = -700
        a = np.zeros(ct_array.shape, dtype=np.uint8)
        a[point] = 1
        ims[name] = sitk.GetImageFromArray(a)
    ct = sitk.GetImageFromArray(ct_array)
    ims["hypopharynx"] = sitk.GetImageFromArray(np.zeros(ct_array.shape, dtype=np.uint8))
    # Only substitute the source loader with an explicit synthetic fixture.
    # The tested candidate/report and real NIfTI write/reread functions remain.
    module.read_case = lambda _root, _case: (ct, ims)
    preview_calls = []
    module.preview = lambda _ct, _original, _extended, _out, case="p3", source_bound=False: preview_calls.append({"case": case, "source_bound": source_bound}) or {"synthetic_preview_stub": True}
    for variant, binding in (("default", None), ("engineering_source_match", {"source_geometry_matches": True})):
        synthetic_out = args.out / ("synthetic_" + variant)
        synthetic_out.mkdir()
        result = module.candidate(Path("SYNTHETIC_ONLY"), "fixture", synthetic_out, source_binding=binding)
        check(variant + ":symptom_patient_mapping", result.get("symptom_patient_mapping"), "unknown")
        check(variant + ":no_B_mapping_key", "patient_B_mapping" in result, False)
        check(variant + ":CFD_not_admitted", result["CFD_admitted"], False)
        check(variant + ":outlet_not_selected", result["outlet_selected"], False)
        check(variant + ":baseline_voxels", result["profiles"]["nasal_original"]["voxels"], 3)
        check(variant + ":extension_voxels", result["profiles"]["nasal_oropharynx"]["voxels"], 4)
    check("preview_receives_engineering_case_and_source_match_only", preview_calls, [{"case": "fixture", "source_bound": False}, {"case": "fixture", "source_bound": True}])
    preview_source = ast.get_source_segment(prototype.read_text(encoding="utf-8"), next(node for node in new_tree.body if isinstance(node, ast.FunctionDef) and node.name == "preview"))
    check("preview_title_symptom_identity_unknown", "symptom identity unknown" in preview_source, True)
    check("preview_title_has_no_B_source_bound_identity", "Patient B" in preview_source, False)
    entry = (repo / "outputs/T-026/执行入口.md").read_text(encoding="utf-8")
    summary = (repo / "outputs/T-026/交付总报告.md").read_text(encoding="utf-8")
    correction = (repo / "outputs/T-026/runs/20261015_06_scope_correction/用户更正.md").read_text(encoding="utf-8")
    check("entry_links_final_summary", "交付总报告.md" in entry, True)
    check("entry_links_scope_correction", "20261015_06_scope_correction/用户更正.md" in entry, True)
    check("summary_symptom_mapping_unknown", "unknown" in summary and "用户撤回" in summary, True)
    check("correction_explicit_all_cases_unknown", "映射全部保持 unknown" in correction, True)
    check("correction_history_sealed_not_rewritten", "历史 run04/run05 不删除、不改写" in correction, True)
    check("frozen_code_unchanged_during_checks", sha(prototype), identities[key_paths[0]])
    # Avoid storing repeated full AST strings in the result, while retaining
    # deterministic hashes for the paired structural comparisons.
    for item in checks:
        if item["name"].startswith("core_AST_"):
            item["actual"] = hashlib.sha256(item["actual"].encode()).hexdigest()
            item["expected"] = hashlib.sha256(item["expected"].encode()).hexdigest()
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "frozen_commit": commit,
              "current_artifact_sha256": identities, "review_script_sha256": sha(__file__),
              "command": [sys.executable, *sys.argv], "checks": checks, "all_pass": all(c["pass"] for c in checks),
              "limits": ["Synthetic identity/algorithm regression only; no repeated patient CT/DICOM read", "Historical run05 engineering HU matching not independently endorsed", "Lead retains acceptance authority"]}
    (args.out / "final_freeze_review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.out / "independent_freeze_review_source_snapshot.py").write_bytes(Path(__file__).read_bytes())
    print(json.dumps({"frozen_commit": commit, "all_pass": report["all_pass"], "check_count": len(checks), "failed": [c for c in checks if not c["pass"]], "hashes": identities}, ensure_ascii=False), flush=True)
    if not report["all_pass"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
