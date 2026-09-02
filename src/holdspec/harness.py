"""The testable transition system: what a merchant can actually do to a PSP.

holdspec.model has actions only the PSP performs (Expire, ReleaseHold, Tick). A
black-box test cannot invoke those; it can only let time pass and observe what
the PSP did. This module wraps the model in the operations a test can issue --
authorize, capture, void, increase authorization, wait -- and says, for each
one, whether a conforming PSP must accept it and what must be observable
afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from . import model as M
from .model import Observation, Op, State
from .profiles import Profile

AUTHORIZE = "authorize"
CAPTURE = "capture"
VOID = "void"
INCREASE_AUTH = "increase_auth"
ADVANCE_TIME = "advance_time"


@dataclass(frozen=True, order=True)
class TestOp:
    """One call a test makes against the system under test."""

    kind: str
    amount: int = 0
    final: bool = True

    def __str__(self) -> str:
        if self.kind == CAPTURE:
            return f"capture({self.amount}, final={self.final})"
        if self.kind in (AUTHORIZE, INCREASE_AUTH):
            return f"{self.kind}({self.amount})"
        if self.kind == ADVANCE_TIME:
            return f"advance_time({self.amount})"
        return f"{self.kind}()"


def call_ops(p: Profile) -> List[TestOp]:
    """Every call a test may issue, arguments included.

    Amounts run one unit past the profile's ceiling on purpose: a capture just
    over the limit is the test that separates a provider honoring its
    over-capture bound from one that does not.
    """
    top = p.max_auth_amount + p.over_capture_allowance + 1
    ops = [TestOp(AUTHORIZE, p.auth_amount), TestOp(VOID), TestOp(ADVANCE_TIME, 1)]
    for c in range(0, top + 1):
        ops.append(TestOp(CAPTURE, c, True))
        if c > 0:
            ops.append(TestOp(CAPTURE, c, False))
    for d in range(1, p.max_auth_amount + 1):
        ops.append(TestOp(INCREASE_AUTH, d))
    return ops


def to_model_op(op: TestOp) -> Optional[Op]:
    if op.kind == AUTHORIZE:
        return Op(M.AUTHORIZE)
    if op.kind == CAPTURE:
        return Op(M.CAPTURE_FINAL if op.final else M.CAPTURE_NON_FINAL, op.amount)
    if op.kind == VOID:
        return Op(M.VOID)
    if op.kind == INCREASE_AUTH:
        return Op(M.INCREASE_AUTH, op.amount)
    return None  # advance_time is not a single model action


def step(p: Profile, s: State, op: TestOp) -> Tuple[bool, State]:
    """Apply `op` to model state `s`.

    Returns (must_be_accepted, resulting state). A rejected call leaves the
    state alone, which is what makes rejection checks cheap to batch.
    """
    if op.kind == ADVANCE_TIME:
        return True, M.settle(p, s, s.clock + op.amount)
    if op.kind == AUTHORIZE and op.amount != p.auth_amount:
        # The model fixes the authorized amount; other amounts are out of scope.
        return False, s
    mop = to_model_op(op)
    assert mop is not None
    nxt = M.apply(p, s, mop)
    if nxt is None:
        return False, s
    return True, nxt


@dataclass(frozen=True)
class Expectation:
    """What a conforming PSP must show after a call."""

    accepted: bool
    observation: Observation
    released: Tuple[int, ...]


def expectation(p: Profile, before: State, op: TestOp) -> Tuple[Expectation, State]:
    accepted, after = step(p, before, op)
    return (
        Expectation(
            accepted=accepted,
            observation=M.observe(after),
            released=tuple(sorted(M.permitted_released(after))),
        ),
        after,
    )


def explore(p: Profile) -> Tuple[Set[State], Dict[State, List[Tuple[TestOp, State]]]]:
    """States a black-box test can drive the PSP into, and how."""
    start = M.initial_state(p)
    seen: Set[State] = {start}
    graph: Dict[State, List[Tuple[TestOp, State]]] = {}
    frontier = [start]
    ops = call_ops(p)
    while frontier:
        nxt_frontier = []
        for s in frontier:
            edges = []
            for op in ops:
                accepted, t = step(p, s, op)
                if accepted and t != s:
                    edges.append((op, t))
            graph[s] = edges
            for _, t in edges:
                if t not in seen:
                    seen.add(t)
                    nxt_frontier.append(t)
        frontier = nxt_frontier
    return seen, graph


def rejecting_ops(p: Profile, s: State) -> List[TestOp]:
    """Calls a conforming PSP must refuse in state `s`."""
    out = []
    for op in call_ops(p):
        accepted, _ = step(p, s, op)
        if not accepted:
            out.append(op)
    return out
