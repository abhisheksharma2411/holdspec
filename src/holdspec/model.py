"""Executable mirror of spec/HoldSpec.tla.

The TLA+ module is the specification of record. This module re-implements the
same state machine in Python so that it can be used for two things TLC cannot
do directly: generating conformance test sequences, and acting as the oracle
that grades a black-box system under test.

Keeping two models honest is a real risk, so experiments/e5_equivalence.py
checks that the set of reachable states here is exactly the set TLC reaches for
the same profile. Any drift between the two shows up as a failed experiment.

Naming follows the TLA+ module: variables and action names are identical, so a
reader can put the two side by side.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Iterator, List, Optional, Set, Tuple

from .profiles import Profile

# Action labels, matching the TLA+ action names.
AUTHORIZE = "Authorize"
CAPTURE_NON_FINAL = "CaptureNonFinal"
CAPTURE_FINAL = "CaptureFinal"
VOID = "Void"
EXPIRE = "Expire"
RELEASE_HOLD = "ReleaseHold"
INCREASE_AUTH = "IncreaseAuth"
TICK = "Tick"
DONE = "Done"

# Actions a merchant can invoke through a PSP API. Expire and ReleaseHold are
# the PSP's own doing and are not callable.
MERCHANT_ACTIONS = (AUTHORIZE, CAPTURE_NON_FINAL, CAPTURE_FINAL, VOID, INCREASE_AUTH)


@dataclass(frozen=True, order=True)
class State:
    state: str = "NONE"
    closedBy: str = "-"
    authAmt: int = 0
    capturedTotal: int = 0
    capturedAtClose: int = 0
    captureCount: int = 0
    lastCaptureAt: int = -1        # NoTime, filled in by initial_state()
    released: int = 0
    expiresAt: int = -1            # NoTime
    releaseDue: int = -1           # NoTime
    clock: int = 0


@dataclass(frozen=True)
class Op:
    """One transition: an action name plus its argument, if it takes one."""

    action: str
    arg: Optional[int] = None

    def __str__(self) -> str:
        return self.action if self.arg is None else f"{self.action}({self.arg})"


def no_time(p: Profile) -> int:
    return p.horizon + 1


def initial_state(p: Profile) -> State:
    nt = no_time(p)
    return State(lastCaptureAt=nt, expiresAt=nt, releaseDue=nt)


def capture_limit(p: Profile, s: State) -> int:
    return s.authAmt + p.over_capture_allowance


def _shortfall(s: State, x: int) -> int:
    return 0 if x >= s.authAmt else s.authAmt - x


def held_amount(s: State) -> int:
    if s.state == "HELD":
        return _shortfall(s, s.capturedTotal)
    if s.released == 0:
        return _shortfall(s, s.capturedAtClose)
    return 0


def release_pending(s: State) -> bool:
    return s.state == "CLOSED" and s.released == 0


def expiry_pending(s: State) -> bool:
    return s.state == "HELD" and s.clock >= s.expiresAt


# --- individual actions -----------------------------------------------------


def _authorize(p: Profile, s: State) -> Optional[State]:
    if s.state != "NONE":
        return None
    return replace(s, state="HELD", authAmt=p.auth_amount, expiresAt=s.clock + p.validity)


def _capture_non_final(p: Profile, s: State, c: int) -> Optional[State]:
    if s.state != "HELD" or s.clock >= s.expiresAt:
        return None
    if s.captureCount >= p.max_non_final_captures:
        return None
    if c <= 0 or s.capturedTotal + c > capture_limit(p, s):
        return None
    # Without a final-capture flag, taking the whole authorized amount ends the
    # hold, so it cannot be a non-final capture. See CaptureNonFinal in the spec.
    if not p.supports_final_capture and s.capturedTotal + c >= s.authAmt:
        return None
    return replace(
        s,
        capturedTotal=s.capturedTotal + c,
        captureCount=s.captureCount + 1,
        lastCaptureAt=s.clock,
    )


def _capture_final(p: Profile, s: State, c: int) -> Optional[State]:
    if s.state != "HELD" or s.clock >= s.expiresAt:
        return None
    if c < 0:
        return None
    if c == 0 and s.captureCount == 0:
        return None
    # An API with no final-capture flag can only close a hold by capturing the
    # whole authorized amount; anything less waits for a cancel or expiry.
    if not p.supports_final_capture and s.capturedTotal + c != s.authAmt:
        return None
    if s.capturedTotal + c > capture_limit(p, s):
        return None
    total = s.capturedTotal + c
    return replace(
        s,
        state="CLOSED",
        closedBy="CAPTURE",
        capturedTotal=total,
        capturedAtClose=total,
        captureCount=s.captureCount + 1,
        lastCaptureAt=s.clock if c > 0 else s.lastCaptureAt,
        releaseDue=s.clock + p.max_release_delay,
    )


def _void(p: Profile, s: State) -> Optional[State]:
    if s.state != "HELD" or s.clock >= s.expiresAt:
        return None
    if s.capturedTotal != 0 and not p.void_after_partial:
        return None
    return replace(
        s,
        state="CLOSED",
        closedBy="VOID",
        capturedAtClose=s.capturedTotal,
        releaseDue=s.clock + p.max_release_delay,
    )


def _expire(p: Profile, s: State) -> Optional[State]:
    if s.state != "HELD" or s.clock < s.expiresAt:
        return None
    return replace(
        s,
        state="CLOSED",
        closedBy="EXPIRY",
        capturedAtClose=s.capturedTotal,
        releaseDue=s.clock + p.max_release_delay,
    )


def _release_hold(p: Profile, s: State) -> Optional[State]:
    if s.state != "CLOSED" or s.released != 0:
        return None
    # releaseDue is kept, not cleared: see the note on ReleaseHold in HoldSpec.tla.
    return replace(s, released=1)


def _increase_auth(p: Profile, s: State, d: int) -> Optional[State]:
    if not p.supports_incremental_auth:
        return None
    if s.state != "HELD" or s.clock >= s.expiresAt:
        return None
    if d <= 0 or s.authAmt + d > p.max_auth_amount:
        return None
    return replace(s, authAmt=s.authAmt + d)


def _tick(p: Profile, s: State) -> Optional[State]:
    if s.state == "NONE" or s.clock >= p.horizon:
        return None
    if expiry_pending(s):
        return None
    if release_pending(s) and s.clock + 1 > s.releaseDue:
        return None
    return replace(s, clock=s.clock + 1)


def _done(p: Profile, s: State) -> Optional[State]:
    if s.clock != p.horizon or s.state == "NONE":
        return None
    if s.state == "CLOSED" and s.released != 1:
        return None
    return s


_DISPATCH = {
    AUTHORIZE: lambda p, s, a: _authorize(p, s),
    CAPTURE_NON_FINAL: lambda p, s, a: _capture_non_final(p, s, a),
    CAPTURE_FINAL: lambda p, s, a: _capture_final(p, s, a),
    VOID: lambda p, s, a: _void(p, s),
    EXPIRE: lambda p, s, a: _expire(p, s),
    RELEASE_HOLD: lambda p, s, a: _release_hold(p, s),
    INCREASE_AUTH: lambda p, s, a: _increase_auth(p, s, a),
    TICK: lambda p, s, a: _tick(p, s),
    DONE: lambda p, s, a: _done(p, s),
}


def apply(p: Profile, s: State, op: Op) -> Optional[State]:
    """Apply `op`, or return None if its guard does not hold in `s`."""
    return _DISPATCH[op.action](p, s, op.arg)


def candidate_ops(p: Profile) -> List[Op]:
    """Every operation the model can be offered, argument values included."""
    top = p.max_auth_amount + p.over_capture_allowance
    ops = [Op(AUTHORIZE), Op(VOID), Op(EXPIRE), Op(RELEASE_HOLD), Op(TICK), Op(DONE)]
    ops += [Op(CAPTURE_NON_FINAL, c) for c in range(1, top + 1)]
    ops += [Op(CAPTURE_FINAL, c) for c in range(0, top + 1)]
    ops += [Op(INCREASE_AUTH, d) for d in range(1, p.max_auth_amount + 1)]
    return ops


def enabled(p: Profile, s: State) -> List[Tuple[Op, State]]:
    """All enabled transitions out of `s`, excluding the terminal self-loop."""
    out = []
    for op in candidate_ops(p):
        if op.action == DONE:
            continue
        nxt = apply(p, s, op)
        if nxt is not None and nxt != s:
            out.append((op, nxt))
    return out


def reachable(p: Profile) -> Tuple[Set[State], Dict[State, List[Tuple[Op, State]]]]:
    """Breadth-first exploration of the reachable state space."""
    start = initial_state(p)
    seen: Set[State] = {start}
    graph: Dict[State, List[Tuple[Op, State]]] = {}
    frontier = [start]
    while frontier:
        nxt_frontier = []
        for s in frontier:
            edges = enabled(p, s)
            graph[s] = edges
            for _, t in edges:
                if t not in seen:
                    seen.add(t)
                    nxt_frontier.append(t)
        frontier = nxt_frontier
    return seen, graph


# --- the black-box view -----------------------------------------------------


@dataclass(frozen=True)
class Observation:
    """What a merchant can see about a hold through a PSP API.

    `released` is deliberately absent as an exact value: the profile allows the
    release of held funds to lag by up to max_release_delay ticks, so the oracle
    checks it against a permitted set rather than a single value.

    Two fields a reader might expect are missing, both because they are not
    provider-neutral.

    The number of capture calls: closing a hold and releasing its remainder is
    a zero-amount capture on Stripe and a cancel on Adyen, so the same abstract
    operation costs a different number of captures depending on the rail. The
    capture budget is still enforced -- as a rejection, which is where a
    merchant actually feels it -- rather than as a counter.

    The reason a hold closed: neither provider reports it synchronously. A
    Stripe PaymentIntent that was voided and one that expired uncaptured both
    read `canceled`, and Adyen answers a cancelled and an expired authorisation
    the same way. Distinguishing the two needs the event stream, so a state
    query cannot be graded on it.
    """

    status: str          # "NONE" | "HELD" | "CLOSED"
    auth_amount: int
    captured_total: int


def observe(s: State) -> Observation:
    return Observation(
        status=s.state,
        auth_amount=s.authAmt,
        captured_total=s.capturedTotal,
    )


def permitted_released(s: State) -> Set[int]:
    """Values of the release counter a conforming PSP may show in state `s`."""
    if s.state != "CLOSED":
        return {0}
    if s.clock > s.releaseDue:
        return {1}
    return {0, 1}


def settle(p: Profile, s: State, target_clock: int) -> State:
    """Advance the clock to `target_clock`, firing the PSP's own actions on time.

    Expiry is urgent: it happens the moment the authorization deadline is
    reached. Releasing held funds may lag, but not past releaseDue, so this
    fires it at the last permitted moment -- the latest behavior a conforming
    PSP may show. `permitted_released` covers the earlier ones.
    """
    cur = s
    guard = 0
    limit = 4 * (p.horizon + 2)
    while cur.clock < min(target_clock, p.horizon):
        guard += 1
        if guard > limit:  # pragma: no cover - structural safety net
            raise RuntimeError("settle did not converge")
        if expiry_pending(cur):
            cur = _expire(p, cur) or cur
            continue
        if release_pending(cur) and cur.clock + 1 > cur.releaseDue:
            cur = _release_hold(p, cur) or cur
            continue
        nxt = _tick(p, cur)
        if nxt is None:
            break
        cur = nxt
    if expiry_pending(cur):
        cur = _expire(p, cur) or cur
    return cur
