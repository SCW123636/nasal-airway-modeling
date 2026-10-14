"""Tests for the run-record artifact fingerprints and the provenance cross-check.

Why these exist: on 2026-10-13 the b02 outlet cap moved 268.51 -> 177.44 between
two batches and the run records (rc/s/tail only) could not say which surface or
which landmarks each batch had actually read. The per-case reports do carry
source_sha256 / plane_source_sha256, but every batch overwrites them, so they are
not a durable record. nasal_pipeline now fingerprints the artifacts it built and
cross-checks them against what the placement report says it read.
"""
import hashlib
import json

import pytest

import nasal_pipeline as NP


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    else:
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                        encoding='utf-8')
    return path


def test_artifact_sha_matches_hashlib(tmp_path):
    f = _write(tmp_path / 'a.bin', b'hello nasal')
    assert NP.artifact_sha(f) == hashlib.sha256(b'hello nasal').hexdigest()


def test_artifact_sha_is_none_when_missing(tmp_path):
    assert NP.artifact_sha(tmp_path / 'nope.bin') is None


def _report(path, surface_sha=None, plane_sha=None, decision='auto_pass',
            areas=None):
    rep = {'decision': decision, 'escalations': [] if decision == 'auto_pass' else
           [{'opening': 'nasopharynx_outlet', 'reason': 'clip_failed'}]}
    if areas is None:
        areas = {'nostril_L': 80.0, 'nostril_R': 80.0, 'nasopharynx_outlet': 260.0}
    rep['patch_areas_mm2'] = areas
    if surface_sha is not None:
        rep['source_sha256'] = surface_sha
    if plane_sha is not None:
        rep['plane_source_sha256'] = plane_sha
    return _write(path, rep)


GOOD = {'nostril_L': 80.0, 'nostril_R': 80.0, 'nasopharynx_outlet': 260.0}


def test_gate_report_matches_provenance(tmp_path):
    p = _report(tmp_path / 'r.json', surface_sha='s1', plane_sha='p1', areas=GOOD)
    out = NP.gate_report('b99', p, surface_sha='s1', plane_sha='p1')
    assert out['ok'] is True
    assert out['provenance'] == {'surface': 'match', 'plane': 'match'}


def test_gate_report_flags_surface_mismatch(tmp_path):
    p = _report(tmp_path / 'r.json', surface_sha='OTHER', plane_sha='p1', areas=GOOD)
    out = NP.gate_report('b99', p, surface_sha='s1', plane_sha='p1')
    assert out['provenance']['surface'] == 'MISMATCH'
    assert out['provenance']['plane'] == 'match'
    # the areas are still reported - they are simply not evidence about s1
    assert out['areas_mm2'] == GOOD


def test_gate_report_unrecorded_when_caller_has_nothing(tmp_path):
    p = _report(tmp_path / 'r.json', areas=GOOD)
    out = NP.gate_report('b99', p)
    assert out['provenance'] == {'surface': 'unrecorded', 'plane': 'unrecorded'}
    assert out['ok'] is True


def test_gate_report_escalated_case_keeps_provenance(tmp_path):
    p = _report(tmp_path / 'r.json', surface_sha='s1', plane_sha='p1',
                decision='escalated')
    out = NP.gate_report('b99', p, surface_sha='s1', plane_sha='p1')
    assert out['ok'] is False
    assert out['decision'] == 'escalated'
    assert out['provenance'] == {'surface': 'match', 'plane': 'match'}


def test_run_case_escalates_on_provenance_mismatch(tmp_path, monkeypatch):
    """A passing-looking report built from other geometry must not pass."""
    opening = tmp_path / 'opening'
    opening.mkdir()
    _report(opening / 'zz_probe.json', surface_sha='STALE', plane_sha='p1',
            areas=GOOD)
    monkeypatch.setattr(NP, 'OPENING_ROOT', opening)
    monkeypatch.setattr(NP, 'mask_check', lambda case: {'gate': 'N2', 'ok': True})
    monkeypatch.setattr(NP, 'run', lambda cmd, timeout: {'rc': 0, 's': 0.1,
                                                         'tail': ''})
    # fingerprints of what this run "built" - deliberately not what the report read
    monkeypatch.setattr(NP, 'artifact_sha',
                        lambda path: 's1' if 'source_surface' in str(path) else 'p1')
    e = NP.run_case('zz_probe', argparse_like())
    assert e['final'] == 'escalated'
    assert e['N6']['ok'] is False
    assert e['N6']['provenance']['surface'] == 'MISMATCH'
    assert e['N6']['areas_mm2'] == GOOD   # reported, but refused


def argparse_like():
    class A:
        device = 'cpu'
        threads = 6
        allow_needs_review = True
        allow_onset_outlier = False
        seed_mode = 'roi'
        search_origin = 'reviewed'
    return A()


def _capture_s5_cmd(monkeypatch):
    """Run run_case with run() stubbed and return the s5 command line.

    run() is called once per stage, so the s5 invocation has to be picked out by
    its script name - grabbing the first call would silently return s3.
    """
    calls = []

    def fake_run(cmd, timeout):
        calls.append([str(c) for c in cmd])
        return {'rc': 0, 's': 0.0, 'tail': ''}

    monkeypatch.setattr(NP, 'run', fake_run)
    monkeypatch.setattr(NP, 'mask_check', lambda case: {'gate': 'N2', 'ok': True})
    monkeypatch.setattr(NP, 'gate_report', lambda *a, **k: {'gate': 'N6', 'ok': True,
                                                            'decision': 'auto_pass'})
    monkeypatch.setattr(NP, 'artifact_sha', lambda path: 'x')
    return calls


def _s5_of(calls):
    s5 = [c for c in calls if any('auto_opening_pipeline.py' in part for part in c)]
    assert len(s5) == 1, f'expected exactly one s5 command, got {len(s5)}'
    return s5[0]


def test_s5_command_carries_the_optin_flags(monkeypatch):
    """The opt-in switches must actually reach the s5 subprocess command line.

    Regression guard: adding --allow-onset-outlier to nasal_pipeline broke the
    run_case fixture (AttributeError) precisely because that coupling was only
    exercised by a hand-run CLI check, not by a test. A flag that is accepted by
    argparse but never forwarded is silently a no-op - the worst kind.
    """
    calls = _capture_s5_cmd(monkeypatch)
    args = argparse_like()
    args.allow_onset_outlier = True
    NP.run_case('zz_probe', args)
    cmd = _s5_of(calls)
    assert '--allow-needs-review' in cmd
    assert '--allow-onset-outlier' in cmd
    assert '--search-origin' in cmd and 'reviewed' in cmd


def test_s5_command_omits_the_optin_flags_by_default(monkeypatch):
    """Default path must stay byte-identical: no flag when the switch is off."""
    calls = _capture_s5_cmd(monkeypatch)
    args = argparse_like()
    args.allow_needs_review = False
    NP.run_case('zz_probe', args)
    cmd = _s5_of(calls)
    assert '--allow-onset-outlier' not in cmd
    assert '--allow-needs-review' not in cmd


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
