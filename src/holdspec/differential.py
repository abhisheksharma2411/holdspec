"""Exhaustive differential search between two PSP implementations.

Two uses, one algorithm:

  * deciding whether a mutant is actually distinguishable from the reference,
    so that an undetected mutant can be reported as equivalent-within-bounds
    rather than as a hole in the suite;
  * finding the shortest call sequence on which two provider profiles disagree,
    which is what the cross-provider comparison reports.

The search walks the product of the two implementations under identical call
sequences and stops at the first observable disagreement. Within the bounds the
profile fixes -- amounts up to the ceiling, time up to the horizon -- the answer
is exact: no difference found means no difference exists in that space.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from .harness import ADVANCE_TIME, AUTHORIZE, CAPTURE, INCREASE_AUTH, VOID, TestOp, call_ops
from .profiles import Profile
from .sut import SUT


def _obs_delta(a, b) -> Tuple[Tuple[str, str, str], ...]:
    """Which attributes of two observations disagree, and how."""
    return tuple(
        (f, str(getattr(a, f)), str(getattr(b, f)))
        for f in ("status", "auth_amount", "captured_total")
        if getattr(a, f) != getattr(b, f)
    )


def _diff(seq, op, field, left, right, differing=()) -> "Difference":
    return Difference(
        sequence=[str(o) for o in seq], op=str(op), field=field,
        left=left, right=right, differing=differing,
        op_kind=op.kind, op_final=op.final, op_amount=op.amount,
    )


def _snapshot(sut: SUT) -> tuple:
    """Canonical, hashable view of a PSP's internal state."""
    d = sut.__dict__
    return tuple(sorted(
        (k, tuple(v) if isinstance(v, list) else v)
        for k, v in d.items()
        if k != "profile"
    ))


def _outcome(sut: SUT, op: TestOp) -> tuple:
    if op.kind == AUTHORIZE:
        res = sut.authorize(op.amount)
    elif op.kind == CAPTURE:
        res = sut.capture(op.amount, op.final)
    elif op.kind == VOID:
        res = sut.void()
    elif op.kind == INCREASE_AUTH:
        res = sut.increase_auth(op.amount)
    elif op.kind == ADVANCE_TIME:
        sut.advance_time(op.amount)
        res = None
    else:
        raise ValueError(op.kind)
    accepted = True if res is None else res.accepted
    return (accepted, sut.observe(), sut.released())


@dataclass
class Difference:
    """A call sequence on which two implementations behave differently."""

    sequence: List[str]
    op: str
    field: str            # "accepted" | "observation" | "released"
    left: str
    right: str
    # For an observation difference, only the attributes that actually differ.
    differing: Tuple[Tuple[str, str, str], ...] = ()
    op_kind: str = ""
    op_final: bool = True
    op_amount: int = 0

    def signature(self) -> tuple:
        """What makes two divergences the same divergence.

        The prefix that reached it does not matter, and neither does the amount:
        a provider that refuses a closing capture refuses it at every amount, and
        listing one class per amount would report one disagreement several times.
        The amounts are kept alongside the class, because for a bound like
        over-capture the amount at which behavior changes is the finding.
        """
        return (
            self.field,
            self.op_kind,
            self.op_final,
            self.differing or ((self.field, self.left, self.right),),
        )

    def script(self) -> str:
        return " ; ".join(self.sequence + [self.op])

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence, "op": self.op, "field": self.field,
            "left": self.left, "right": self.right, "script": self.script(),
            "length": len(self.sequence) + 1,
        }


def _clone(sut: SUT) -> SUT:
    """Copy a PSP's state without re-running the call sequence that built it."""
    twin = sut.__class__(sut.profile)
    for k, v in sut.__dict__.items():
        if k == "profile":
            continue
        setattr(twin, k, list(v) if isinstance(v, list) else v)
    return twin


def find_difference(
    left: Callable[[], SUT],
    right: Callable[[], SUT],
    ops_profile: Profile,
    max_states: int = 500_000,
) -> Optional[Difference]:
    """Shortest call sequence distinguishing `left` from `right`, if one exists.

    Breadth-first over the product of the two implementations, so the sequence
    returned is of minimum length. Within the profile's bounds the search is
    exhaustive: returning None means no distinguishing sequence exists there.
    """
    ops = call_ops(ops_profile)
    start_l, start_r = left(), right()
    start_l.reset()
    start_r.reset()
    seen = {(_snapshot(start_l), _snapshot(start_r))}
    queue: deque = deque([([], start_l, start_r)])

    while queue and len(seen) < max_states:
        seq, base_l, base_r = queue.popleft()
        for op in ops:
            l, r = _clone(base_l), _clone(base_r)
            out_l = _outcome(l, op)
            out_r = _outcome(r, op)
            if out_l[0] != out_r[0]:
                return _diff(seq, op, "accepted",
                             "accepted" if out_l[0] else "rejected",
                             "accepted" if out_r[0] else "rejected")
            if out_l[1] != out_r[1]:
                return _diff(seq, op, "observation", str(out_l[1]), str(out_r[1]),
                             _obs_delta(out_l[1], out_r[1]))
            if out_l[2] != out_r[2]:
                return _diff(seq, op, "released", str(out_l[2]), str(out_r[2]))
            key = (_snapshot(l), _snapshot(r))
            if key not in seen:
                seen.add(key)
                queue.append((seq + [op], l, r))
    return None


def is_equivalent(
    mutant: Callable[[], SUT], reference: Callable[[], SUT], profile: Profile
) -> Tuple[bool, Optional[Difference]]:
    diff = find_difference(mutant, reference, profile)
    return diff is None, diff


def find_all_differences(
    left: Callable[[], SUT],
    right: Callable[[], SUT],
    ops_profile: Profile,
    max_states: int = 500_000,
    max_differences: int = 500,
) -> List[Difference]:
    """Every way the two implementations can be told apart, not just the first.

    When a call distinguishes them the search records it and does not follow
    that call, because past a divergence the two are in different states and
    everything downstream is a consequence of the same disagreement. Exploration
    continues along the calls on which they still agree, so what comes back is
    the set of independent divergences reachable within the profile's bounds.
    """
    ops = call_ops(ops_profile)
    start_l, start_r = left(), right()
    start_l.reset()
    start_r.reset()
    seen = {(_snapshot(start_l), _snapshot(start_r))}
    queue: deque = deque([([], start_l, start_r)])
    found: List[Difference] = []

    while queue and len(seen) < max_states and len(found) < max_differences:
        seq, base_l, base_r = queue.popleft()
        for op in ops:
            l, r = _clone(base_l), _clone(base_r)
            out_l = _outcome(l, op)
            out_r = _outcome(r, op)
            diff = None
            if out_l[0] != out_r[0]:
                diff = _diff(seq, op, "accepted",
                             "accepted" if out_l[0] else "rejected",
                             "accepted" if out_r[0] else "rejected")
            elif out_l[1] != out_r[1]:
                diff = _diff(seq, op, "observation", str(out_l[1]), str(out_r[1]),
                             _obs_delta(out_l[1], out_r[1]))
            elif out_l[2] != out_r[2]:
                diff = _diff(seq, op, "released", str(out_l[2]), str(out_r[2]))
            if diff is not None:
                found.append(diff)
                continue
            key = (_snapshot(l), _snapshot(r))
            if key not in seen:
                seen.add(key)
                queue.append((seq + [op], l, r))
    return found


def group_differences(diffs: List[Difference]) -> List[dict]:
    """Collapse divergences that are the same disagreement reached differently."""
    groups: dict = {}
    for d in diffs:
        key = d.signature()
        prev = groups.get(key)
        if prev is None or len(d.sequence) < len(prev.sequence):
            groups[key] = d
    out = []
    for key, witness in groups.items():
        members = [d for d in diffs if d.signature() == key]
        out.append(
            {
                "field": witness.field,
                "op_kind": witness.op_kind,
                "op_final": witness.op_final,
                "amounts": sorted({d.op_amount for d in members}),
                "differing": [
                    {"attribute": f, "left": lv, "right": rv} for f, lv, rv in key[3]
                ],
                "left": witness.left,
                "right": witness.right,
                "witness": witness.script(),
                "witness_length": len(witness.sequence) + 1,
                "instances": len(members),
            }
        )
    out.sort(key=lambda r: (r["witness_length"], r["field"], r["op_kind"]))
    return out
