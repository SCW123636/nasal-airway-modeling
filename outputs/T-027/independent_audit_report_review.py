"""Compare T-026 five-case report to separately recomputed T-027 evidence."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import numpy as np


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--independent-audit", type=Path, required=True)
    p.add_argument("--author-run", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    checks, compact = [], []

    def check(name, actual, expected):
        checks.append({"name": name, "actual": actual, "expected": expected, "pass": actual == expected})

    def close(name, actual, expected):
        check(name, bool(np.allclose(actual, expected, rtol=0, atol=1e-8)), True)

    for own in load(args.independent_audit):
        case = own["case"]
        author = load(args.author_run / (case + "_audit.json"))
        geometry = own["ct"]["geometry"]
        check(case + ":CT_size_xyz", author["CT"]["size_xyz"], geometry["size_xyz"])
        close(case + ":CT_spacing", author["CT"]["spacing_xyz_mm"], geometry["spacing_xyz_mm"])
        close(case + ":CT_origin", author["CT"]["origin_LPS_mm"], geometry["origin_lps_mm"])
        close(case + ":CT_direction", author["CT"]["direction_row_major"], geometry["direction_row_major"])
        close(case + ":CT_support_LPS_bounds", author["CT"]["voxel_support_bounds_LPS_mm"], [own["ct"]["support_min_lps_mm"], own["ct"]["support_max_lps_mm"]])
        for label, item in own["labels"].items():
            claimed = author["labels"][label]
            prefix = case + ":" + label + ":"
            check(prefix + "existence", claimed["exists"], item["exists"])
            if not item["exists"]:
                continue
            check(prefix + "same_grid", claimed["same_grid_as_CT"], item["compatible"])
            for kind, author_key in (("semantic", "semantic"), ("air_strict_lt_minus300", "air_HU_lt_minus300")):
                own_mask, author_mask = item[kind], claimed[author_key]
                sub = prefix + kind + ":"
                check(sub + "voxel_count", author_mask["voxels"], own_mask["nonzero_voxels"])
                check(sub + "empty", author_mask["empty"], own_mask["nonzero_voxels"] == 0)
                close(sub + "volume_mm3", author_mask["volume_mm3"], own_mask["volume_mm3"])
                if own_mask["nonzero_voxels"]:
                    close(sub + "centre_bounds", author_mask["center_bounds_LPS_mm"], [own_mask["centre_min_lps_mm"], own_mask["centre_max_lps_mm"]])
                    close(sub + "support_bounds", author_mask["bounds_LPS_mm"], [own_mask["support_min_lps_mm"], own_mask["support_max_lps_mm"]])
                    check(sub + "boundary_contact", author_mask["boundary_contact"]["any"], own_mask["touches_any_grid_face"])
                    own_faces = {axis + "_" + side: own_mask["face_voxel_counts"][axis + "_index_" + index] for axis in "xyz" for side, index in (("low", "0"), ("high", "last"))}
                    check(sub + "face_voxel_counts", author_mask["boundary_contact"]["face_voxel_counts"], own_faces)
                else:
                    check(sub + "empty_bounds", author_mask["bounds_LPS_mm"], None)
                    check(sub + "empty_contact_has_no_anatomical_meaning", author_mask["boundary_contact"], None)
        compact.append({"case": case, "CT_size_xyz": geometry["size_xyz"], "spacing_xyz_mm": geometry["spacing_xyz_mm"],
                        "baseline_air_voxels": own["independent_sets"]["air_baseline"]["nonzero_voxels"],
                        "added_oropharynx_air_voxels": own["independent_sets"]["oropharynx_air_added"]["nonzero_voxels"],
                        "extended_air_voxels": own["independent_sets"]["air_extended"]["nonzero_voxels"],
                        "oropharynx_air_z0_face_voxels": own["labels"]["oropharynx"]["air_strict_lt_minus300"]["face_voxel_counts"]["z_index_0"],
                        "hypopharynx_semantic_voxels": own["labels"]["hypopharynx"]["semantic"]["nonzero_voxels"],
                        "larynx_air_exists": own["labels"]["larynx_air"]["exists"]})
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "command": [sys.executable, *sys.argv],
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "independent_raw_audit_sha256": hashlib.sha256(args.independent_audit.read_bytes()).hexdigest(),
              "compact_results": compact, "checks": checks, "all_pass": all(c["pass"] for c in checks)}
    (args.out / "five_case_report_comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.out / "independent_audit_report_review_source_snapshot.py").write_bytes(Path(__file__).read_bytes())
    print(json.dumps({"checks": len(checks), "all_pass": report["all_pass"], "failed": [c for c in checks if not c["pass"]], "compact_results": compact}, ensure_ascii=False), flush=True)
    if not report["all_pass"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
