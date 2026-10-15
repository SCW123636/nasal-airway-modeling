"""T-042: extract patient functional metrics from the T-041 b15 maxh1 S-A run.

Runs AFTER the b15_maxh1 simpleFoam run reaches endTime 600. Never re-solves.
The ORIGINAL case is never modified -- not even with derived artifacts: every
write happens inside a fresh copy at /home/lenovo2/t042_b15_wssfix/.

Pipeline (all WSL commands are VARIABLE-FREE; see trap 1):
  0    confirm the resume log shows End
  0b   verify patch_map manifest against live boundary-condition counts
  1    rm -rf t042_b15_wssfix && cp -r b15_maxh1 t042_b15_wssfix
       && rm -rf t042_b15_wssfix/VTK        (drop the stale zero-WSS VTK gen)
  2    patch_wall_type.py --patch wall      (trap 4: type patch -> type wall)
  3    cp log.simpleFoam_resume -> log.simpleFoam inside the copy
       (the extractor hardcodes log.simpleFoam; the real one is the stale
       run killed at Time=317, the resume log is the live one)
  4    postProcessing: per-patch names -> extractor's flow_/pressure_ names,
       stale legacy flowIn/pressureIn dirs removed (trap 2)
  5    cp b15_patch_map.json -> t042_b15_wssfix/case_manifest.json (trap 3)
  6    simpleFoam -postProcess -func wallShearStress -latestTime
  7    foamToVTK -ascii
  8    extract_cfd_metrics.py --case t042_b15_wssfix
  9    copy the metrics JSON back to Windows + audit against KNOWN VALUES

Traps this script is built around (all hit for real on 2026-10-15/16)
--------------------------------------------------------------------
(1) NAMED SHELL VARIABLES ARE EATEN between Windows and WSL.  A command like
    `for f in CASE/*; do ln -s "$f" SCRATCH/; done` reaches WSL bash with an
    EMPTY `$f` (every iteration then fails with
    "failed to create symbolic link 'SCRATCH/' -> ''").  `$?` and `$0`
    survive, `$f`/`$p`/any named variable does not.  FIX: every command below
    is variable-free (literal paths, `echo RC=$?` is the only $-form and it
    is a special parameter, verified to survive).
(2) THE EXTRACTOR'S LEGACY dat FALLBACK WOULD SILENTLY DEGRADE TO Float32.
    dat_value() tries flow_<patch>/pressure_<patch> first, then the legacy
    per-role names flowIn/pressureIn/flowOut/pressureOut.  This case's
    controlDict defines only per-patch objects (flowInL/flowInR/flowOut/
    pressureInL/pressureInR/pressureOut); the legacy flowIn/ and pressureIn/
    directories are STALE ARTIFACTS of the pre-restart configuration with
    EMPTY dat files -> last_dat_value returns None -> double-precision
    function-object data is silently skipped in favour of VTK Float32.
    FIX (step 4): copy the per-patch output into the copy's postProcessing
    under the extractor's documented names (flowInL -> flow_nostril_L, ...).
    Renames of the case's own output; no value is altered.
(3) PATCH ROLE HEURISTICS: extract_cfd_metrics.infer_roles classifies
    nostril_L/nostril_R as wall (no 'inlet' substring) -> "need at least one
    inlet and one outlet" abort.  FIX (step 5): case_manifest.json carrying
    patch_map, whose role evidence (BC types) is verified against the live
    case in step 0b BEFORE any extraction.  The guard fired once already, on
    a wrong expectation vector written by the author, and correctly refused.
(4) wallShearStress SILENTLY WRITES ZERO unless the patch is `type wall`.
    gmshToFoam builds every patch as `type patch`; the original case's
    VTK/b15_maxh1_600/boundary/wall.vtp carries wallShearStress that is ALL
    "0 0 0" and the extractor reported wall_shear_force_n = 0.0 N without
    any error.  FIX (step 2): patch_wall_type.py rewrites the wall block to
    `type wall; inGroups 1(wall);` in the COPY (nFaces/startFace untouched,
    delta_p verified bit-identical against the unpatched run).  Note the
    corollary for idempotency checks: "wallShearStress field present" is NOT
    proof the post-processing ran correctly -- zero values are present too.
(5) foamToVTK NAMES ITS OUTPUT AFTER THE CASE DIRECTORY (t042_b15_wssfix ->
    VTK/t042_b15_wssfix_600) and latest_vtk_dir picks max((time, name)):
    copying a case forward can leave the OLD zero-WSS generation
    (b15_maxh1_600) inside VTK/ and the tie-break is alphabetical.
    FIX (step 1): the stale VTK/ is deleted from the copy so exactly one
    generation exists.

Known values (authoritative run 2026-10-15T16:57:32Z, case t042_b15_wssfix):
step 9 re-derives the metrics and refuses to overwrite outputs/T-042/
metrics_b15_maxh1.json unless every field below matches BIT-FOR-BIT.  A
mismatch means the pipeline is not reproducible -- that is a bug in THIS
script, not a new result, and the previous file is kept.

Output: outputs/T-042/metrics_b15_maxh1.json (+ metrics_b15_maxh1.raw.txt
with the raw step log, for auditing).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CASE = "/home/lenovo2/patient_cfd/b15_maxh1"
FIXCASE = "/home/lenovo2/t042_b15_wssfix"
MANIFEST_WIN = REPO / "outputs" / "T-042" / "b15_patch_map.json"
OUT = REPO / "outputs" / "T-042" / "metrics_b15_maxh1.json"
RAW = REPO / "outputs" / "T-042" / "metrics_b15_maxh1.raw.txt"
WSL = ["wsl.exe", "-d", "Ubuntu-22.04", "--"]

# authoritative values, metrics_b15_maxh1.json generated_at 2026-10-15T16:57:32Z
EXPECTED = [
    (["metrics", "delta_p_pa", "value"], 10.286010671888477),
    (["metrics", "delta_p_pa", "p_in_kinematic"], 8.571675559907064),
    (["metrics", "delta_p_pa", "p_out_kinematic"], 0.0),
    (["metrics", "delta_p_pa", "source"], "function_object_dat"),
    (["metrics", "resistance_R", "value_pa_s_ml"], 0.04114404268755391),
    (["metrics", "wall_shear_force_n", "value_n"], 0.0011019165435884187),
    (["metrics", "split_ratio", "value"], 0.5),
    (["metrics", "mass_imbalance_frac"], 5.272055999226699e-07),
    (["metrics", "max_velocity_mps", "value"], 4.569027257461373),
    (["metrics", "total_flow_m3s", "value"], 0.00025),
    (["metrics", "outlet_flow_m3s", "value"], 0.0002499998681986),
    (["source", "vtk_time_dir"], "t042_b15_wssfix_600"),
]
EXPECTED_SHA = {
    "VTK/t042_b15_wssfix_600/boundary/nasopharynx_outlet.vtp":
        "9ab9f64be3f903996868de5ed554bf99327d6b755022eda2c8524480b3ff720d",
    "VTK/t042_b15_wssfix_600/boundary/nostril_L.vtp":
        "f28a262f55172a0258aab109017eb5e2ab518d2a2ae09a65e4cb2f55ca90cfc8",
    "VTK/t042_b15_wssfix_600/boundary/nostril_R.vtp":
        "5b27c4407406be12c59f0785b8edec6573a11d442ac47d186efa8f490494d535",
    "VTK/t042_b15_wssfix_600/boundary/wall.vtp":
        "0c12945f1f15773eeb004968fe625e6b284d699dd0d5691174fc64d534187b2b",
    "VTK/t042_b15_wssfix_600/internal.vtu":
        "dbb4e46aa961e156952991ed4a003231c049f0e445aa5d570edc8ccd7f4105ea",
    "log.simpleFoam":
        "ef66cd42702fd8ad7baa125e99339e3fbc1e6f3f5e970a82c57d1e612ddb0bbe",
}


def sh(args, timeout=3600):
    r = subprocess.run(WSL + args, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


def finish(steps, status, reason, code):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    (REPO / "outputs" / "T-042" / "metrics_b15_maxh1.raw.txt").write_text(
        json.dumps({"status": status, "reason": reason, "steps": steps},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(status.upper() + ": " + reason)
    return code


def main():
    steps = []

    # 0. solver must have reached End (resume log is the live one)
    rc, out = sh(["bash", "-c", "cd %s && tail -2 log.simpleFoam_resume" % CASE], 120)
    steps.append({"step": "confirm_solver_finished", "rc": rc, "tail": out[-400:]})
    if "End" not in out:
        return finish(steps, "aborted",
                      "solver log does not show End; run not finished", 1)

    # 0b. verify the patch_map manifest against the live boundary conditions
    #     expected, from 0/U and 0/p of this case:
    #       flowRateInletVelocity x2 (nostril_L, nostril_R)  in 0/U
    #       noSlip x1 (wall)                                  in 0/U
    #       fixedValue x1 (nasopharynx_outlet, p=0)           in 0/p
    #       zeroGradient x1 (nasopharynx_outlet)              in 0/U
    rc, out = sh(["bash", "-c",
                  "cd %s && grep -c flowRateInletVelocity 0/U && grep -c noSlip 0/U "
                  "&& grep -c fixedValue 0/p && grep -c zeroGradient 0/U" % CASE], 120)
    counts = [int(t) for t in out.split() if t.isdigit()]
    steps.append({"step": "verify_bc_counts_for_manifest", "rc": rc, "tail": out[-200:]})
    if counts != [2, 1, 1, 1]:
        return finish(steps, "aborted",
                      "BC counts %r do not match patch_map evidence [2,1,1,1]; "
                      "refusing to extract with an unverified role map" % (counts,), 1)

    # 1. rebuild the extraction copy.  Idempotency probe FIRST: a complete,
    #    correctly-post-processed copy is reused (the probe demands NON-ZERO
    #    WSS, not merely a wallShearStress field -- see trap 4/5).
    rc, out = sh(["bash", "-c",
                  "cd %s && test -f VTK/t042_b15_wssfix_600/boundary/wall.vtp "
                  "&& grep -A2 wallShearStress VTK/t042_b15_wssfix_600/boundary/wall.vtp "
                  "| grep -qv '0 0 0' && test -f postProcessing/pressure_nostril_L/200/surfaceFieldValue.dat "
                  "&& test -f case_manifest.json && test -f log.simpleFoam "
                  "&& test -f 600/wallShearStress && echo READY || echo REBUILD" % FIXCASE], 300)
    steps.append({"step": "probe_fixcase_ready", "rc": rc, "tail": out[-200:]})
    if "READY" in out:
        steps.append({"step": "rebuild_copy", "skipped": True,
                      "note": "existing t042_b15_wssfix copy is complete and carries non-zero WSS"})
    else:
        # 1a. fresh copy without the stale zero-WSS VTK generation (trap 5)
        rc, out = sh(["bash", "-c",
                      "rm -rf %s && cp -r %s %s && rm -rf %s/VTK && echo COPIED"
                      % (FIXCASE, CASE, FIXCASE, FIXCASE)], 900)
        steps.append({"step": "copy_case_without_vtk", "rc": rc, "tail": out[-300:]})
        if "COPIED" not in out:
            return finish(steps, "error", "case copy failed", 2)

        # 1b. wall patch type (trap 4).  patch_wall_type.py lives in the repo
        #     and runs on the WSL side with python3 (stdlib only).
        rc, out = sh(["bash", "-c",
                      "cp /mnt/d%s /home/lenovo2/t042_patch_wall.py && "
                      "cd /home/lenovo2 && python3 t042_patch_wall.py --case %s "
                      "--patch wall --type wall --group wall 2>&1 | tail -30"
                      % (REPO.as_posix()[2:] + "/work/lib/patch_wall_type.py", FIXCASE)], 300)
        steps.append({"step": "patch_wall_type", "rc": rc, "tail": out[-800:]})
        if "rewritten" not in out and "no-op" not in out:
            return finish(steps, "error", "patch_wall_type did not report success", 2)
        # the original case must be untouched
        rc, out = sh(["bash", "-c",
                      "grep -c 'type            patch;' %s/constant/polyMesh/boundary" % CASE], 120)
        steps.append({"step": "verify_original_case_untouched", "rc": rc, "tail": out[-100:]})
        if out.strip() != "4":
            return finish(steps, "error",
                          "original case boundary no longer has 4 'type patch' entries; "
                          "the copy must never touch the source case", 2)

        # 1c. the extractor hardcodes log.simpleFoam; the live log is the resume one
        rc, out = sh(["bash", "-c",
                      "cp %s/log.simpleFoam_resume %s/log.simpleFoam && echo COPIED"
                      % (FIXCASE, FIXCASE)], 120)
        steps.append({"step": "resume_log_in_place", "rc": rc, "tail": out[-100:]})
        if "COPIED" not in out:
            return finish(steps, "error", "resume log copy failed", 2)

        # 1d. per-patch function-object dirs -> extractor names; drop stale
        #     legacy dirs whose empty dat would silently degrade to Float32 (trap 2)
        rc, out = sh(["bash", "-c",
                      "cd %s/postProcessing && "
                      "mv flowInL flow_nostril_L && mv flowInR flow_nostril_R && "
                      "mv flowOut flow_nasopharynx_outlet && "
                      "mv pressureInL pressure_nostril_L && mv pressureInR pressure_nostril_R && "
                      "mv pressureOut pressure_nasopharynx_outlet && "
                      "rm -rf flowIn pressureIn && ls | tr '\\n' ' '"
                      % FIXCASE], 300)
        steps.append({"step": "remap_function_object_dirs", "rc": rc, "tail": out[-300:]})
        if rc != 0 or "pressure_nostril_L" not in out:
            return finish(steps, "error", "function-object dir remap failed", 2)

        # 1e. patch_map manifest into the copy (the real case never sees it)
        rc, out = sh(["bash", "-c",
                      "cp /mnt/d%s %s/case_manifest.json && echo COPIED"
                      % (MANIFEST_WIN.as_posix()[2:], FIXCASE)], 120)
        steps.append({"step": "install_patch_map_manifest", "rc": rc, "tail": out[-200:]})
        if "COPIED" not in out:
            return finish(steps, "error", "manifest copy failed", 2)

        # 1f. wallShearStress field (needs type wall, trap 4) + ascii VTK
        rc, out = sh(["bash", "-c",
                      "cd %s && source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1 "
                      "&& simpleFoam -postProcess -func wallShearStress -latestTime "
                      "> log.postProcess 2>&1; echo RC=$?" % FIXCASE], 3600)
        steps.append({"step": "postProcess -func wallShearStress", "rc": rc, "tail": out[-600:]})
        if "RC=0" not in out:
            return finish(steps, "error", "postProcess wallShearStress failed", 2)
        rc, out = sh(["bash", "-c",
                      "cd %s && source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1 "
                      "&& foamToVTK -ascii > log.foamToVTK 2>&1; echo RC=$?" % FIXCASE], 3600)
        steps.append({"step": "foamToVTK -ascii", "rc": rc, "tail": out[-600:]})
        if "RC=0" not in out:
            return finish(steps, "error", "foamToVTK failed", 2)

    # 2. extract inside WSL (case on native FS; ~1.16M cells, ascii VTK)
    rc, out = sh(["bash", "-c",
                  "cp /mnt/d%s /home/lenovo2/t042_extract.py && "
                  "cd /home/lenovo2 && python3 t042_extract.py --case %s "
                  "--out /home/lenovo2/t042_b15_wssfix_metrics.json 2>&1 | tail -20"
                  % (REPO.as_posix()[2:] + "/work/lib/extract_cfd_metrics.py", FIXCASE)], 3600)
    steps.append({"step": "extract_cfd_metrics", "rc": rc, "tail": out[-1200:]})
    if rc != 0:
        return finish(steps, "error", "extractor failed: " + out[-400:], 2)

    # 3. pull the JSON back
    dest = "/mnt/d" + (REPO / "outputs" / "T-042" / "t042_b15_metrics.json").as_posix()[2:]
    rc, out = sh(["bash", "-c",
                  "cp /home/lenovo2/t042_b15_wssfix_metrics.json %s && echo COPIED" % dest], 300)
    steps.append({"step": "copy_json_back", "rc": rc, "tail": out[-300:]})
    if "COPIED" not in out:
        return finish(steps, "error", "copying metrics json back failed", 2)

    m = json.loads((REPO / "outputs" / "T-042" / "t042_b15_metrics.json").read_text(encoding="utf-8"))

    # 4. known-value audit: reproduce or refuse (see module docstring)
    mismatches = []
    for path, want in EXPECTED:
        got = m
        for part in path:
            got = got.get(part) if isinstance(got, dict) else None
            if got is None:
                break
        if got != want:
            mismatches.append("%s: got %r want %r" % (".".join(path), got, want))
    for rel, want in EXPECTED_SHA.items():
        got = m["source"]["inputs_sha256"].get(rel)
        if got != want:
            mismatches.append("sha %s: got %r want %r" % (rel, got, want))
    if m["case"]["name"] != "t042_b15_wssfix":
        mismatches.append("case.name: got %r want t042_b15_wssfix" % m["case"]["name"])
    if mismatches:
        (REPO / "outputs" / "T-042" / "metrics_b15_maxh1.repro_fail.json").write_text(
            json.dumps({"mismatches": mismatches, "got": m}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        return finish(steps, "error",
                      "reproduction audit FAILED (%d mismatches); previous metrics file kept; "
                      "see metrics_b15_maxh1.repro_fail.json" % len(mismatches), 3)

    OUT.write_text(json.dumps(m, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    RAW.write_text(json.dumps({"status": "ok", "reason": "reproduced bit-for-bit",
                               "steps": steps}, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print("REPRODUCED: all %d known values + %d input hashes match bit-for-bit"
          % (len(EXPECTED), len(EXPECTED_SHA)))
    print(json.dumps({
        "delta_p_pa": m["metrics"]["delta_p_pa"]["value"],
        "delta_p_source": m["metrics"]["delta_p_pa"]["source"],
        "resistance_pa_s_ml": m["metrics"]["resistance_R"]["value_pa_s_ml"],
        "wall_shear_force_n": m["metrics"]["wall_shear_force_n"].get("value_n"),
        "split_ratio": m["metrics"]["split_ratio"].get("value"),
        "mass_imbalance_frac": m["metrics"]["mass_imbalance_frac"],
        "converged_residualControl": m["metrics"]["converged"],
        "max_velocity_mps": m["metrics"]["max_velocity_mps"]["value"],
        "warnings": m["warnings"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
