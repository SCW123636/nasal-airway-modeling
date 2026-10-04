"""Run a longer straight-tube phantom to separate entrance effects from S1-S3.

The original 40 mm phantom remains the strict baseline and is never overwritten.
This companion uses the same solver chain and tolerances with L/D=40, so the
fully developed section occupies most of the tube. It is diagnostic evidence,
not a replacement for the original baseline.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path

import phantom_validation as base

L_MM = 160.0
WORK_DIR_DEFAULT = r"C:\ts_work\phantom_validation_developed"


@contextmanager
def configured():
    original = base.L_MM
    try:
        base.L_MM = L_MM
        yield
    finally:
        base.L_MM = original


def prepare(work_dir):
    with configured():
        return base.prepare(work_dir)


def run_cases(work_dir):
    with configured():
        return base.run_cases(work_dir)


def collect(work_dir):
    with configured():
        status = base.collect(work_dir)
    if status == 2:
        return status
    report = json.loads((Path(work_dir) / "validation.json").read_text(encoding="utf-8"))
    report["experiment"] = {
        "kind": "developed_length_diagnostic",
        "baseline_report": "../phantom_validation/validation.json",
        "purpose": "Separate short-tube entrance development from the solver/mesh chain; not a patient validation result.",
        "L_over_D": L_MM / base.D_MM,
        "controlled_change": "Tube length only: 40 to 160 mm; diameter, total flow, surface refinement and solver settings unchanged.",
    }
    (Path(work_dir) / "validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default=WORK_DIR_DEFAULT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--collect", action="store_true")
    args = parser.parse_args(argv)
    if args.prepare:
        return prepare(args.work_dir)
    if args.run:
        return run_cases(args.work_dir)
    return collect(args.work_dir)


if __name__ == "__main__":
    raise SystemExit(main())
