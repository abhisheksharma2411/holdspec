"""Unit and sanity checks for the model, the oracle, and the adapters.

Run with `python -m pytest tests` or `python tests/test_holdspec.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import pytest  # noqa: E402

from holdspec import model as M  # noqa: E402
from holdspec.differential import find_difference  # noqa: E402
from holdspec.generator import handwritten_suite, model_suite, random_suite  # noqa: E402
from holdspec.harness import (ADVANCE_TIME, AUTHORIZE, CAPTURE, VOID, TestOp,  # noqa: E402
                              explore, rejecting_ops, step)
from holdspec.model import Op, initial_state, reachable  # noqa: E402
from holdspec.mutants import MUTANTS  # noqa: E402
from holdspec.profiles import (ALL_PROFILES, BY_NAME, P_ADYEN_MULTIPLE_PARTIAL,  # noqa: E402
                               P_STRIPE_DEFAULT, P_STRIPE_MULTICAPTURE,
                               P_STRIPE_OVERCAPTURE)
from holdspec.runner import run_suite  # noqa: E402
from holdspec.sut import ReferencePSP  # noqa: E402


# --- the model's own invariants hold in every reachable state ---------------

@pytest.mark.parametrize("profile", ALL_PROFILES, ids=lambda p: p.name)
def test_invariants_hold_in_every_reachable_state(profile):
    states, _ = reachable(profile)
    for s in states:
        assert s.capturedTotal <= s.authAmt + profile.over_capture_allowance
        assert s.released <= 1
        if s.state != "CLOSED":
            assert s.released == 0
        else:
            assert s.capturedTotal == s.capturedAtClose
            if s.released == 0:
                assert s.clock <= s.releaseDue
        if s.capturedTotal > 0:
            assert s.lastCaptureAt < s.expiresAt
        assert s.captureCount <= profile.max_non_final_captures + 1
        if s.state == "CLOSED" and s.released == 1:
            assert M.held_amount(s) == 0


@pytest.mark.parametrize("profile", ALL_PROFILES, ids=lambda p: p.name)
def test_every_reachable_state_is_closed_and_released_somewhere(profile):
    """The lifecycle can always be finished, not just started."""
    states, _ = reachable(profile)
    assert any(s.state == "CLOSED" and s.released == 1 for s in states)
    assert any(s.closedBy == "EXPIRY" for s in states)
    assert any(s.closedBy == "CAPTURE" for s in states)
    assert any(s.closedBy == "VOID" for s in states)


# --- documented provider rules show up as model behavior --------------------

def test_stripe_default_allows_only_one_capture():
    p = P_STRIPE_DEFAULT
    s = M.apply(p, initial_state(p), Op(M.AUTHORIZE))
    s2 = M.apply(p, s, Op(M.CAPTURE_FINAL, 1))
    assert s2 is not None and s2.state == "CLOSED"
    assert M.apply(p, s2, Op(M.CAPTURE_FINAL, 1)) is None
    assert M.apply(p, s, Op(M.CAPTURE_NON_FINAL, 1)) is None


def test_stripe_partial_capture_releases_the_remainder():
    p = P_STRIPE_DEFAULT
    s = M.apply(p, initial_state(p), Op(M.AUTHORIZE))
    s = M.apply(p, s, Op(M.CAPTURE_FINAL, 1))
    settled = M.settle(p, s, p.horizon)
    assert settled.released == 1
    assert M.held_amount(settled) == 0


def test_multicapture_keeps_the_hold_open_until_a_final_capture():
    p = P_STRIPE_MULTICAPTURE
    s = M.apply(p, initial_state(p), Op(M.AUTHORIZE))
    s = M.apply(p, s, Op(M.CAPTURE_NON_FINAL, 1))
    assert s.state == "HELD" and s.capturedTotal == 1
    s = M.apply(p, s, Op(M.CAPTURE_FINAL, 0))       # release the remainder
    assert s.state == "CLOSED" and s.capturedTotal == 1


def test_over_capture_is_bounded_by_the_profile():
    p = P_STRIPE_OVERCAPTURE
    s = M.apply(p, initial_state(p), Op(M.AUTHORIZE))
    assert M.apply(p, s, Op(M.CAPTURE_FINAL, p.auth_amount + 1)) is not None
    assert M.apply(p, s, Op(M.CAPTURE_FINAL, p.auth_amount + 2)) is None


def test_adyen_multi_has_no_final_capture_flag():
    """Closing short of the full amount is a cancel there, not a capture."""
    p = P_ADYEN_MULTIPLE_PARTIAL
    s = M.apply(p, initial_state(p), Op(M.AUTHORIZE))
    s = M.apply(p, s, Op(M.CAPTURE_NON_FINAL, 1))
    assert M.apply(p, s, Op(M.CAPTURE_FINAL, 1)) is None    # would leave a remainder
    assert M.apply(p, s, Op(M.CAPTURE_FINAL, 3)) is not None  # takes the whole amount
    assert M.apply(p, s, Op(M.VOID)) is not None              # cancel the remainder


def test_no_capture_at_or_after_the_expiry_instant():
    for p in ALL_PROFILES:
        s = M.apply(p, initial_state(p), Op(M.AUTHORIZE))
        s = M.settle(p, s, p.validity)
        assert s.state == "CLOSED" and s.closedBy == "EXPIRY"
        assert M.apply(p, s, Op(M.CAPTURE_FINAL, 1)) is None


# --- the oracle and the suites ---------------------------------------------

@pytest.mark.parametrize("profile", ALL_PROFILES, ids=lambda p: p.name)
def test_reference_passes_every_suite(profile):
    for name, tests, neg in (
        ("model", model_suite(profile), True),
        ("handwritten", handwritten_suite(profile), False),
        ("random", random_suite(profile, 2000, 7), True),
    ):
        report = run_suite(lambda: ReferencePSP(profile), profile, tests, name, include_negative=neg)
        assert report.failed == 0, f"{profile.name}/{name}: {report.violations[:1]}"


@pytest.mark.parametrize("profile", ALL_PROFILES, ids=lambda p: p.name)
def test_model_suite_reaches_every_testable_state(profile):
    states, _ = explore(profile)
    covered = set()
    for test in model_suite(profile):
        s = initial_state(profile)
        covered.add(s)
        for op in test.ops:
            _, s = step(profile, s, op)
            covered.add(s)
    assert covered == states


def test_rejected_calls_do_not_move_the_model():
    p = P_STRIPE_MULTICAPTURE
    s = M.apply(p, initial_state(p), Op(M.AUTHORIZE))
    for op in rejecting_ops(p, s):
        accepted, after = step(p, s, op)
        assert not accepted and after == s


@pytest.mark.parametrize("profile", ALL_PROFILES, ids=lambda p: p.name)
def test_every_non_equivalent_mutant_is_killed(profile):
    suite = model_suite(profile)
    for cls in MUTANTS:
        equivalent = find_difference(
            lambda cls=cls: cls(profile), lambda: ReferencePSP(profile), profile
        ) is None
        if equivalent:
            continue
        report = run_suite(lambda cls=cls: cls(profile), profile, suite, "model", stop_after=1)
        assert report.detected, f"{profile.name}: {cls.name} survived"


def test_differential_search_finds_the_documented_provider_gap():
    """Stripe accepts a closing capture below the full amount; Adyen does not."""
    left, right = BY_NAME["stripe_multicapture"], BY_NAME["adyen_multiple_partial_captures"]
    diff = find_difference(
        lambda: ReferencePSP(left), lambda: ReferencePSP(right), left
    )
    assert diff is not None
    assert diff.field == "accepted"


def test_settle_is_idempotent_at_the_horizon():
    for p in ALL_PROFILES:
        s = M.apply(p, initial_state(p), Op(M.AUTHORIZE))
        once = M.settle(p, s, p.horizon)
        assert M.settle(p, once, p.horizon) == once


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
