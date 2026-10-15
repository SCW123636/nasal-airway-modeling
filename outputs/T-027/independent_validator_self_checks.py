"""Known answers for T-027's own measurement and comparison criteria."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import SimpleITK as sitk

root = Path(__file__).parent
spec = importlib.util.spec_from_file_location("own_auditor", root / "independent_input_audit.py")
own = importlib.util.module_from_spec(spec)
spec.loader.exec_module(own)
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=False)
im = sitk.GetImageFromArray(np.zeros((3, 4, 5), dtype=np.uint8))
im.SetSpacing((2, 3, 4))
im.SetOrigin((10, 20, 30))
im.SetDirection((0, -1, 0, 1, 0, 0, 0, 0, -1))
mask = np.zeros((3, 4, 5), dtype=bool)
mask[0, 1, 2] = True  # LPS=(7,24,30)
mask[2, 3, 4] = True  # LPS=(1,28,22)
summary = own.foreground_summary(mask, im)
checks = []

def check(name, actual, expected):
    checks.append({"name": name, "actual": actual, "expected": expected, "pass": actual == expected})

check("known_foreground_count", summary["nonzero_voxels"], 2)
check("known_volume_mm3", summary["volume_mm3"], 48.0)
check("known_centre_min", summary["centre_min_lps_mm"], [1.0, 24.0, 22.0])
check("known_centre_max", summary["centre_max_lps_mm"], [7.0, 28.0, 30.0])
check("known_support_min", summary["support_min_lps_mm"], [-0.5, 23.0, 20.0])
check("known_support_max", summary["support_max_lps_mm"], [8.5, 29.0, 32.0])
check("known_boundary_face_counts", summary["face_voxel_counts"], {"x_index_0": 0, "x_index_last": 1, "y_index_0": 0, "y_index_last": 1, "z_index_0": 1, "z_index_last": 1})
empty = own.foreground_summary(np.zeros_like(mask), im)
check("empty_label_not_anatomical_absence", (empty["nonzero_voxels"], empty["centre_min_lps_mm"]), (0, None))
shifted = sitk.Image(im)
shifted.SetOrigin((10, 20, 30.01))
check("own_grid_match_positive", all(own.matches(im, im).values()), True)
check("own_grid_match_negative_shift", all(own.matches(im, shifted).values()), False)
flipped = sitk.Image(im)
flipped.SetDirection((1, 0, 0, 0, 1, 0, 0, 0, 1))
check("own_grid_match_negative_direction", all(own.matches(im, flipped).values()), False)
tampered = mask.copy()
tampered[1, 1, 1] = True
tampered[0, 1, 2] = False
check("own_per_voxel_criterion_detects_added_and_removed", int(np.count_nonzero(tampered != mask)), 2)
check("own_subset_criterion_detects_removed_source", int(np.count_nonzero(mask & ~tampered)), 1)
check("own_source_criterion_detects_unlabelled_extra", int(np.count_nonzero(tampered & ~mask)), 1)
report = {"all_pass": all(c["pass"] for c in checks), "checks": checks,
          "known_answer_source": "Two explicit voxels with manually stated LPS centres and half-voxel support in this source; deliberate mask corruption and geometry mismatches.",
          "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          "auditor_sha256": hashlib.sha256((root / "independent_input_audit.py").read_bytes()).hexdigest(),
          "command": [sys.executable, *sys.argv]}
(out / "own_validator_known_answers.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(out / "independent_validator_self_checks_source_snapshot.py").write_bytes(Path(__file__).read_bytes())
print(json.dumps(report, ensure_ascii=False), flush=True)
sys.exit(0 if report["all_pass"] else 1)
