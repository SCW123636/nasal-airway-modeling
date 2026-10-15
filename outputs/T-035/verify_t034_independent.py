"""T-035 faithful re-derivation of T-034 run02.

Replicates run_scope_probe.py's exact method (allowed = nostril barrier planes
extended to LPS support bounds; ext sentinel = y0/z0/zN/yN faces), then compares
core numbers with probe-run02.json. Also reports the methodology caveat that the
engineering_screen_pass is tautological w.r.t. the ROI extension.
"""
from __future__ import annotations
import sys, json, copy, itertools
import numpy as np
import SimpleITK as sitk
from scipy import ndimage

ROOT = r"D:\项目\鼻腔建模"
CT_PATH = r"C:\ts_work\p3\ct.nii.gz"
SEED_PATH = r"C:\ts_work\t034_continuous_air\run01\semantic_air_original.nii.gz"
PLANES = ROOT + r"\work\06_auto_landmarks\p3\review_config_proposed.json"
ARTIFACT = ROOT + r"\outputs\T-034\probe-run02.json"

sys.path.insert(0, ROOT + r"\work\lib")
from continuous_air_candidate import connected_air, face_contacts, index_to_lps, same_grid
from anatomy_barrier_seg import plane_keep_mask


def main() -> int:
    image = sitk.ReadImage(CT_PATH)
    ct = sitk.GetArrayFromImage(image)
    seed_im = sitk.ReadImage(SEED_PATH)
    seed = sitk.GetArrayFromImage(seed_im) > 0
    if not same_grid(image, seed_im):
        raise RuntimeError("seed grid mismatch")

    # LPS support bounds (identical to run02)
    corners = np.array(list(itertools.product(*[(-.5, n - .5) for n in image.GetSize()])))
    world = index_to_lps(corners, image)
    lo = world.min(0)
    print(f"[bounds] LPS support lo = {lo.tolist()}")

    config = json.load(open(PLANES, encoding="utf-8"))
    allowed = np.ones(ct.shape, bool)
    for name in ("nostril_L", "nostril_R"):
        original = config["planes_lps"][name]
        p = copy.deepcopy(original)
        p["roi_lps_mm"]["min"][1] = float(lo[1])   # extend y-min to support bound
        p["roi_lps_mm"]["min"][2] = float(lo[2])   # extend z-min to support bound
        keep = plane_keep_mask(image, p, ct.shape)
        allowed &= keep
        print(f"[allowed] after {name}: kept voxels = {int(allowed.sum())}")

    # ext sentinel: y0, z0, zN, yN faces (NOT x faces) — identical to run02 line 69
    ext = np.zeros(ct.shape, bool)
    ext[:, :, 0] = True
    ext[:, :, -1] = True
    ext[:, 0, :] = True
    ext[:, -1, :] = True

    candidate, facts = connected_air(ct, seed, allowed, ext, reject_leak=False)
    facts["face_contacts"] = face_contacts(candidate)
    facts["added_vs_original_seed_voxels"] = int((candidate & ~seed).sum())
    facts["removed_vs_original_seed_voxels"] = int((seed & ~candidate).sum())

    print(f"[components] air_component_count (within allowed) = {facts['air_component_count']}")
    print(f"[seed] seed_component_ids = {facts['seed_component_ids']}")
    print(f"[candidate] candidate_voxels = {facts['candidate_voxels']}")
    print(f"[candidate] added = {facts['added_vs_original_seed_voxels']}")
    print(f"[candidate] removed = {facts['removed_vs_original_seed_voxels']}")
    print(f"[leak] exterior_leak_detected = {facts.get('exterior_leak_detected')}")
    print(f"[screen] engineering_screen_pass = {not facts.get('exterior_leak_detected')}")
    # does candidate (allowed-region flood) still touch the x faces (lateral)?
    print(f"[leak] candidate touches x0/xN (lateral scan faces) = {bool(candidate[:,:,0].any())}/{bool(candidate[:,:,-1].any())}")

    art = json.load(open(ARTIFACT, encoding="utf-8"))["candidate"]
    checks = {
        "air_component_count": (facts["air_component_count"], art["air_component_count"]),
        "seed_component_ids": (sorted(facts["seed_component_ids"]), sorted(art["seed_component_ids"])),
        "candidate_voxels": (facts["candidate_voxels"], art["candidate_voxels"]),
        "added_vs_eligible_seed_voxels": (facts["added_vs_original_seed_voxels"], art["added_vs_eligible_seed_voxels"]),
    }
    print("\n=== COMPARISON vs probe-run02.json (faithful method) ===")
    all_ok = True
    for name, (got, exp) in checks.items():
        ok = got == exp
        all_ok = all_ok and ok
        print(f"  {name}: got={got}  expected={exp}  {'OK' if ok else 'MISMATCH'}")
    # Note: eligible_seed_voxels differs slightly because artifact removed 1722 voxels
    # outside allowed before counting; report both
    print(f"  [note] eligible_seed (this re-derivation, seed&air within allowed) = {int((seed & (ct < -300) & allowed).sum())}  (artifact removed 1722 first -> 443870)")
    print(f"\nVERDICT: faithful-method re-derivation {'MATCHES' if all_ok else 'DOES NOT MATCH'} artifact")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
