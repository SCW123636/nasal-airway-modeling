"""Strict, case-bound review contract for airway boundaries.

The landmark review answers where a candidate plane is.  This module records
the separate modelling decisions that determine what is kept in the fluid
domain: oral exclusion, sinus policy, and the three numerical openings.  The
record is deliberately independent from the geometry builder and never
unlocks a mesh or a solver by itself.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import uuid


SCHEMA = "boundary_review/v1"
OPENINGS = ("nostril_L", "nostril_R", "nasopharynx_outlet")
EVIDENCE = ("axial", "coronal", "sagittal", "oral_overlay", "sinus_overlay", "openings_overlay")
IDENTITY_FIELDS = ("case", "patient_id", "revision", "ct_sha256", "label_sha256",
                   "candidate_sha256", "landmark_review_sha256")
REVISION_RE = re.compile(r"(?:original|v_[0-9a-f]{16})\Z")
SHA256_RE = re.compile(r"[0-9a-fA-F]{64}\Z")


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text(value, name, errors, *, max_length=256):
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        errors.append(f"{name} must be a non-empty string")
        return None
    return value.strip()


def _hash(value, name, errors):
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        errors.append(f"{name} must be a SHA-256 hex digest")
        return None
    return value.lower()


def _vector(value, name, errors, *, nonzero=False):
    result = None
    if (isinstance(value, list) and len(value) == 3
            and all(not isinstance(item, bool) and isinstance(item, (int, float)) for item in value)):
        try:
            result = [float(item) for item in value]
        except (OverflowError, ValueError):
            pass
    if result is None or not all(math.isfinite(item) for item in result):
        errors.append(f"{name} must contain three finite numbers")
        return None
    if nonzero and math.hypot(*result) <= 1e-12:
        errors.append(f"{name} must be non-zero")
    return result


def _roi(value, name, errors):
    if not isinstance(value, dict):
        errors.append(f"{name} must contain min and max bounds")
        return
    lower = _vector(value.get("min"), name + ".min", errors)
    upper = _vector(value.get("max"), name + ".max", errors)
    if lower is not None and upper is not None:
        if any(a >= b for a, b in zip(lower, upper)):
            errors.append(f"{name}.min must be lower than max on every axis")


def _cutting_plane(value, name, errors):
    if not isinstance(value, dict):
        errors.append(f"{name} must be an object")
        return
    _vector(value.get("point_lps_mm"), name + ".point_lps_mm", errors)
    _vector(value.get("normal_lps"), name + ".normal_lps", errors, nonzero=True)
    _roi(value.get("roi_lps_mm"), name + ".roi_lps_mm", errors)
    if not isinstance(value.get("keep_positive"), bool):
        errors.append(f"{name}.keep_positive must be boolean")


def _plane(value, name, errors, *, status="confirmed"):
    _cutting_plane(value, name, errors)
    if isinstance(value, dict) and value.get("status") != status:
        errors.append(f"{name}.status must be {status}")


def validate_cutting_planes(openings, oral):
    """Validate numerical draft controls without inventing a human confirmation."""
    errors = []
    if not isinstance(openings, dict) or set(openings) != set(OPENINGS):
        errors.append("openings must contain exactly the three numerical boundaries")
    else:
        for key in OPENINGS:
            _cutting_plane(openings[key], f"openings.{key}", errors)
    if not isinstance(oral, dict):
        errors.append("oral_exclusion must be an object")
    elif oral.get("mode") == "same_as_nasopharynx_outlet":
        if oral.get("boundary_ref") != "nasopharynx_outlet":
            errors.append("oral_exclusion.boundary_ref must reference nasopharynx_outlet")
    elif oral.get("mode") == "separate_plane":
        _cutting_plane(oral.get("boundary"), "oral_exclusion.boundary", errors)
    else:
        errors.append("oral_exclusion.mode is invalid")
    if errors:
        raise ValueError("cutting controls validation failed: " + "; ".join(errors))


def _timestamp(value, name, errors):
    text = _text(value, name, errors, max_length=80)
    if text is not None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                errors.append(f"{name} must include a timezone")
        except ValueError:
            errors.append(f"{name} must be an ISO-8601 timestamp")


def _compare(expected, actual, name, errors):
    if expected is not None and actual != expected:
        errors.append(f"{name} does not match the current case identity")


def geometry_parameters(record):
    """Hash the actual cutting controls, independent of review prose and time."""
    def controls(plane):
        return {key: plane[key] for key in
                ("point_lps_mm", "normal_lps", "roi_lps_mm", "keep_positive")}
    oral = record["oral_exclusion"]
    sinus = record["sinus_policy"]
    return {
        "openings": {key: controls(record["openings"][key]) for key in OPENINGS},
        "oral_exclusion": {"mode": oral["mode"], **(
            {"boundary_ref": oral["boundary_ref"]}
            if oral["mode"] == "same_as_nasopharynx_outlet"
            else {"boundary": controls(oral["boundary"])})},
        "sinus_policy": {key: sinus[key] for key in ("policy", "regions", "mask_sha256")},
    }


def parameters_sha256(record):
    payload = json.dumps(geometry_parameters(record), sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_record(record: dict, expected: dict | None = None) -> dict:
    """Validate a complete boundary review and its current input identity.

    ``expected`` is supplied by the case runner.  It contains the current
    case, revision, CT hash, label hash map, candidate hash and landmark
    review hash.  A missing expected value is not silently filled from the
    submitted record; this keeps stale reviews from being accepted by a
    caller that forgot to load the current receipt.
    """
    errors: list[str] = []
    if not isinstance(record, dict):
        raise ValueError("boundary_review must be a JSON object")
    if record.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    case = _text(record.get("case"), "case", errors)
    patient = _text(record.get("patient_id"), "patient_id", errors)
    revision = _text(record.get("revision"), "revision", errors, max_length=32)
    if revision is not None and not REVISION_RE.fullmatch(revision):
        errors.append("revision must be original or v_<16 lowercase hex>")
    if record.get("coordinate_system") != "LPS":
        errors.append("coordinate_system must be LPS")
    if record.get("unit") != "mm":
        errors.append("unit must be mm")
    if record.get("status") != "confirmed":
        errors.append("status must be confirmed")
    if record.get("method") != "human":
        errors.append("method must be human")
    _text(record.get("reviewer"), "reviewer", errors)
    _timestamp(record.get("reviewed_at"), "reviewed_at", errors)

    source = record.get("source")
    if not isinstance(source, dict):
        errors.append("source must be an object")
        source = {}
    source_revision = _text(source.get("revision"), "source.revision", errors, max_length=32)
    if source_revision is not None and not REVISION_RE.fullmatch(source_revision):
        errors.append("source.revision is invalid")
    if revision is not None:
        _compare(revision, source_revision, "source.revision", errors)
    ct_hash = _hash(source.get("ct_sha256"), "source.ct_sha256", errors)
    candidate_hash = _hash(source.get("candidate_sha256"), "source.candidate_sha256", errors)
    landmark_hash = _hash(source.get("landmark_review_sha256"),
                          "source.landmark_review_sha256", errors)
    _hash(source.get("draft_preview_sha256"), "source.draft_preview_sha256", errors)
    _hash(source.get("parameters_sha256"), "source.parameters_sha256", errors)
    labels = source.get("label_sha256")
    if not isinstance(labels, dict) or not labels:
        errors.append("source.label_sha256 must be a non-empty object")
        labels = {}
    for label, digest in labels.items():
        if not isinstance(label, str) or not label.strip():
            errors.append("source.label_sha256 keys must be non-empty strings")
        _hash(digest, f"source.label_sha256[{label!r}]", errors)

    openings = record.get("openings")
    if not isinstance(openings, dict):
        errors.append("openings must be an object")
        openings = {}
    if set(openings) != set(OPENINGS):
        errors.append("openings must contain exactly the three numerical boundaries")
    for opening in OPENINGS:
        _plane(openings.get(opening), f"openings.{opening}", errors)

    oral = record.get("oral_exclusion")
    if not isinstance(oral, dict):
        errors.append("oral_exclusion must be an object")
        oral = {}
    if oral.get("confirmed") is not True:
        errors.append("oral_exclusion.confirmed must be true")
    mode = oral.get("mode")
    if not isinstance(mode, str) or mode not in {"same_as_nasopharynx_outlet", "separate_plane"}:
        errors.append("oral_exclusion.mode is invalid")
    if mode == "same_as_nasopharynx_outlet":
        if oral.get("boundary_ref") != "nasopharynx_outlet":
            errors.append("oral_exclusion.boundary_ref must reference nasopharynx_outlet")
    else:
        _plane(oral.get("boundary"), "oral_exclusion.boundary", errors)
    _text(oral.get("evidence"), "oral_exclusion.evidence", errors, max_length=2000)

    sinus = record.get("sinus_policy")
    if not isinstance(sinus, dict):
        errors.append("sinus_policy must be an object")
        sinus = {}
    if sinus.get("confirmed") is not True:
        errors.append("sinus_policy.confirmed must be true")
    if sinus.get("policy") != "exclude_sinuses":
        errors.append("sinus_policy.policy must be exclude_sinuses for G_main")
    regions = sinus.get("regions")
    if not isinstance(regions, list) or not regions or any(
            not isinstance(item, str) or not item.strip() for item in regions):
        errors.append("sinus_policy.regions must list the considered sinus regions")
    _text(sinus.get("evidence"), "sinus_policy.evidence", errors, max_length=2000)
    _hash(sinus.get("mask_sha256"), "sinus_policy.mask_sha256", errors)
    evidence = record.get("evidence_sha256")
    if not isinstance(evidence, dict) or set(evidence) != set(EVIDENCE):
        errors.append("evidence_sha256 must identify all CT and boundary overlays")
        evidence = {}
    for key, digest in evidence.items():
        _hash(digest, f"evidence_sha256.{key}", errors)

    if not errors and source["parameters_sha256"] != parameters_sha256(record):
        errors.append("source.parameters_sha256 does not match cutting controls")

    if expected is not None:
        required = set(IDENTITY_FIELDS) | {"draft_preview_sha256", "parameters_sha256",
                                          "evidence_sha256", "sinus_mask_sha256"}
        if not isinstance(expected, dict) or any(expected.get(key) is None for key in required):
            errors.append("expected must contain the complete current case and draft identity")
        expected = expected if isinstance(expected, dict) else {}
    else:
        expected = {}
    _compare(expected.get("case"), case, "case", errors)
    _compare(expected.get("patient_id"), patient, "patient_id", errors)
    _compare(expected.get("revision"), revision, "revision", errors)
    _compare(expected.get("ct_sha256"), ct_hash, "source.ct_sha256", errors)
    _compare(expected.get("candidate_sha256"), candidate_hash,
             "source.candidate_sha256", errors)
    _compare(expected.get("landmark_review_sha256"), landmark_hash,
             "source.landmark_review_sha256", errors)
    expected_labels = expected.get("label_sha256")
    if expected_labels is not None:
        if labels != expected_labels:
            errors.append("source.label_sha256 does not match the current labels")
    for key in ("draft_preview_sha256", "parameters_sha256"):
        _compare(expected.get(key), source.get(key), "source." + key, errors)
    _compare(expected.get("evidence_sha256"), evidence, "evidence_sha256", errors)
    _compare(expected.get("sinus_mask_sha256"), sinus.get("mask_sha256"),
             "sinus_policy.mask_sha256", errors)

    if errors:
        raise ValueError("boundary_review validation failed: " + "; ".join(errors))
    return record


def load_boundary_review(path: str | os.PathLike[str], expected: dict | None = None) -> dict:
    path = Path(path)
    record = json.loads(path.read_text(encoding="utf-8"))
    return validate_record(record, expected=expected)


def write_boundary_review(path: str | os.PathLike[str], record: dict,
                          expected: dict | None = None) -> dict:
    """Validate and atomically publish a boundary review JSON."""
    validate_record(record, expected=expected)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2,
                                        allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return record


__all__ = [
    "OPENINGS", "EVIDENCE", "IDENTITY_FIELDS", "SCHEMA", "load_boundary_review", "sha256_file",
    "geometry_parameters", "parameters_sha256",
    "validate_cutting_planes", "validate_record", "write_boundary_review",
]
