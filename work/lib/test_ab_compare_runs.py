"""Regression tests for the A/B comparison gate.

Why this file exists: on 2026-10-13 ab_compare_runs.py hardcoded
ANCHOR_FAILED = {b04, b23} together with the *reason* those cases were blocked
("both are anchor failures"). The change under test falsified exactly that
premise, so the tool reported `verdict: FAIL` for a correct change - a gate
whose output is well-formed but wrong. Reference points:

  * a gate must not encode per-case conclusions as constants; if it does, it
    silently converts "the premise changed" into "the change is wrong";
  * the fix keeps arm-agnostic invariants (bit-identical areas for cases that
    already passed, no newly failing case) always on, and takes arm-specific
    expectations as arguments.

These tests pin both halves: the invariants must still fire, and the
expectations must come from the caller.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import ab_compare_runs as AB  # noqa: E402


def _row(final, areas=None, reasons=None):
    n6 = {'areas_mm2': areas}
    if reasons is not None:
        n6['escalations'] = [{'opening': o, 'reason': r} for o, r in reasons]
    return {'final': final, 'N6': n6}


A = {'nostril_L': 80.0, 'nostril_R': 80.0, 'nasopharynx_outlet': 250.0}


def _write(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text(json.dumps(rows), encoding='utf-8')
    return str(p)


@pytest.fixture
def runs(tmp_path):
    """baseline 21/24 (b04/b23/b20 escalated); candidate 22/24 (b23 passes)."""
    base = {
        'b01': _row('auto_pass', dict(A)),
        'b04': _row('escalated', reasons=[('nasopharynx_outlet', 'onset_outlier')]),
        'b20': _row('escalated', reasons=[(None, 'no_planes')]),
        'b23': _row('escalated', reasons=[('nasopharynx_outlet', 'onset_outlier')]),
    }
    cand = {
        'b01': _row('auto_pass', dict(A)),
        'b04': _row('escalated', reasons=[('nostril_L', 'seed_lost'),
                                          ('nasopharynx_outlet', 'seed_lost')]),
        'b20': _row('escalated', reasons=[(None, 'no_planes')]),
        'b23': _row('auto_pass', dict(A)),
    }
    return _write(tmp_path, 'base.json', base), _write(tmp_path, 'cand.json', cand)


def test_default_still_fails_on_the_historical_blocked_set(runs, capsys):
    """The built-in expectation must NOT be weakened: with no arguments the
    historical blocked set still applies, so b23 passing is a VIOLATION."""
    base, cand = runs
    AB.main([base, cand])
    out = capsys.readouterr().out
    assert 'b23 (expected blocked) must NOT pass: auto_pass  VIOLATION' in out
    assert 'verdict: FAIL' in out


def test_caller_can_declare_the_new_expectation(runs, capsys):
    base, cand = runs
    AB.main([base, cand, '--expect-pass', 'b23', '--reasons-clean', 'b04'])
    out = capsys.readouterr().out
    assert 'b23 (expected to pass) must pass: auto_pass  OK' in out
    assert 'b04 reason must not be onset_outlier' in out
    assert 'OK' in out.split('b04 reason must not be onset_outlier')[1].split('\n')[0]
    assert 'verdict: PASS' in out


def test_expect_pass_removes_the_case_from_blocked(runs, capsys):
    """A caller cannot accidentally assert both blocked and expected-to-pass:
    --expect-pass wins, otherwise the tool would always fail."""
    base, cand = runs
    AB.main([base, cand, '--expect-pass', 'b23'])
    out = capsys.readouterr().out
    assert 'b23 (expected blocked)' not in out
    assert 'verdict: PASS' in out


def test_bit_identical_invariant_still_fires(tmp_path, capsys):
    """Arm-agnostic: if a change moves a case that already passed, that is a
    failure regardless of any expectation the caller declares."""
    base = {'b01': _row('auto_pass', dict(A))}
    cand = {'b01': _row('auto_pass', dict(A, nostril_L=81.0))}
    AB.main([_write(tmp_path, 'b.json', base), _write(tmp_path, 'c.json', cand)])
    out = capsys.readouterr().out
    assert 'MISMATCH' in out
    assert 'verdict: FAIL' in out


def test_newly_failing_invariant_still_fires(tmp_path, capsys):
    """Arm-agnostic: auto_pass -> escalated is always a regression, even when
    the caller declares no expectations at all."""
    base = {'b01': _row('auto_pass', dict(A))}
    cand = {'b01': _row('escalated', reasons=[('nostril_L', 'seed_lost')])}
    AB.main([_write(tmp_path, 'b.json', base), _write(tmp_path, 'c.json', cand),
             '--no-blocked-defaults'])
    out = capsys.readouterr().out
    assert 'previously passing cases now failing:' in out
    assert 'REGRESSION' in out
    assert 'verdict: FAIL' in out


def test_blocked_override_replaces_defaults(runs, capsys):
    base, cand = runs
    AB.main([base, cand, '--expect-blocked', 'b04'])
    out = capsys.readouterr().out
    assert 'b20 (expected blocked)' not in out
    assert 'b23 (expected blocked)' not in out
    assert 'verdict: PASS' in out
