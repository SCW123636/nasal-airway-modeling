"""The onset_outlier gate demotion, tested on both sides.

Why this test exists: the gate blocks any opening whose lumen onset falls outside
[-4, +1] mm - a band read off the five pilot cases. It guarded the *onset-anchored*
placement search. Since 2026-10-13 the default origin is `reviewed`, so the onset
no longer drives any position, and a direct A/B (probe_onset_gate_bypass.py) showed
the gate is a strict no-op on every in-band case, blocks b23 even though the
reviewed-anchored search reaches an in-band cap, and that b04 escalates anyway with
its real reason (`seed_lost`). Demoting it therefore loses no safety.

The three outcomes must stay distinct, because conflating them is exactly how this
project's criteria have shipped broken before:

  * in band                  -> no note at all
  * out of band, gate on     -> escalate (onset_outlier)
  * out of band, gate off    -> flag only (onset_outlier), placement decides
  * onset is None            -> escalate (no_onset) either way: a missing onset is
                                a degenerate-geometry signal, not a start-offset one
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_opening_pipeline as A


def test_in_band_needs_no_note():
    bucket, note = A.onset_verdict('nostril_L', -0.25, allow_onset_outlier=False)
    assert (bucket, note) == (None, None)


@pytest.mark.parametrize('onset', [-4.0, 1.0, 0.0, -1.75])
def test_band_edges_are_inclusive(onset):
    """The band is closed; a value sitting exactly on an edge is not an outlier."""
    bucket, note = A.onset_verdict('nasopharynx_outlet', onset, False)
    assert (bucket, note) == (None, None)


@pytest.mark.parametrize('onset', [-4.01, 1.01, -7.25, -5.0, -3.25 - 1.0])
def test_out_of_band_escalates_when_gate_on(onset):
    bucket, note = A.onset_verdict('nasopharynx_outlet', onset, False)
    assert bucket == 'escalate'
    assert note['reason'] == 'onset_outlier'
    assert note['opening'] == 'nasopharynx_outlet'
    assert 'outside the band' in note['detail']


@pytest.mark.parametrize('onset', [-7.25, -5.0])
def test_out_of_band_only_flags_when_gate_demoted(onset):
    """Same observation, same note - only the bucket changes."""
    _, on = A.onset_verdict('nasopharynx_outlet', onset, False)
    bucket, off = A.onset_verdict('nasopharynx_outlet', onset, True)
    assert bucket == 'flag'
    assert off == on, 'demotion must not drop or rewrite the observation'


def test_missing_onset_always_escalates():
    """no_onset is a hard block regardless of the demotion switch."""
    for allow in (False, True):
        bucket, note = A.onset_verdict('nostril_R', None, allow)
        assert bucket == 'escalate'
        assert note['reason'] == 'no_onset'


def test_demotion_is_opt_in_by_default():
    import inspect
    sig = inspect.signature(A.process)
    assert sig.parameters['allow_onset_outlier'].default is False


def test_cli_exposes_both_switches():
    """Both entry points must offer the switch, spelled the same way."""
    for path in (Path(__file__).resolve().parent / 'auto_opening_pipeline.py',
                 Path(__file__).resolve().parent / 'nasal_pipeline.py'):
        text = path.read_text(encoding='utf-8')
        assert "'--allow-onset-outlier'" in text, path.name


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
