"""Building conformance suites from the model, plus the baselines to beat."""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import model as M
from .harness import (ADVANCE_TIME, AUTHORIZE, CAPTURE, INCREASE_AUTH, VOID,
                      TestOp, call_ops, explore, step)
from .model import State
from .profiles import Profile


@dataclass
class TestCase:
    name: str
    ops: List[TestOp] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.ops)


def _bfs_tree(p: Profile) -> Tuple[Dict[State, Optional[Tuple[State, TestOp]]],
                                   Dict[State, List[Tuple[TestOp, State]]]]:
    start = M.initial_state(p)
    _, graph = explore(p)
    parent: Dict[State, Optional[Tuple[State, TestOp]]] = {start: None}
    queue = deque([start])
    while queue:
        s = queue.popleft()
        for op, t in graph[s]:
            if t not in parent:
                parent[t] = (s, op)
                queue.append(t)
    return parent, graph


def _path_to(parent: Dict[State, Optional[Tuple[State, TestOp]]], s: State) -> List[TestOp]:
    ops: List[TestOp] = []
    cur = s
    while parent[cur] is not None:
        prev, op = parent[cur]
        ops.append(op)
        cur = prev
    ops.reverse()
    return ops


def model_suite(p: Profile) -> List[TestCase]:
    """A suite covering every reachable state and every accepted transition.

    Construction: the breadth-first tree over the testable state space gives one
    test per leaf, which walks a maximal chain of transitions. Transitions the
    tree does not use -- edges back to states already reached -- get one short
    test each. The runner checks the model's expectation after every call, so a
    test that is a prefix of another adds nothing and is left out.
    """
    parent, graph = _bfs_tree(p)
    children: Dict[State, int] = {s: 0 for s in parent}
    tree_edges = set()
    for s, entry in parent.items():
        if entry is not None:
            prev, op = entry
            children[prev] = children.get(prev, 0) + 1
            tree_edges.add((prev, op, s))

    tests: List[TestCase] = []
    for s in parent:
        if children.get(s, 0) == 0:  # leaf of the BFS tree
            tests.append(TestCase(f"path_{len(tests)}", _path_to(parent, s)))

    for s, edges in graph.items():
        for op, t in edges:
            if (s, op, t) not in tree_edges:
                tests.append(TestCase(f"edge_{len(tests)}", _path_to(parent, s) + [op]))
    return tests


def random_suite(
    p: Profile, api_call_budget: int, seed: int, include_negative: bool = True
) -> List[TestCase]:
    """Random call sequences, matched to a suite's API-call budget.

    The comparison is about how call sequences get chosen, so what is held fixed
    is the number of calls made against the system under test -- rejection
    checks included, since those cost a call too. Budgeting by sequence length
    instead would hand the random arm several times the traffic and measure
    something else.
    """
    from .harness import rejecting_ops

    rng = random.Random(seed)
    ops = call_ops(p)
    tests: List[TestCase] = []
    spent = 0
    while spent < api_call_budget:
        length = rng.randint(1, max(2, p.horizon + 3))
        seq: List[TestOp] = []
        s = M.initial_state(p)
        cost = 0
        for _ in range(length):
            if include_negative:
                cost += len(rejecting_ops(p, s))
            cost += 1
            op = rng.choice(ops)
            seq.append(op)
            _, s = step(p, s, op)
            if spent + cost >= api_call_budget:
                break
        if include_negative:
            cost += len(rejecting_ops(p, s))
        if not seq:
            break
        tests.append(TestCase(f"rand_{len(tests)}", seq))
        spent += cost
    return tests


def handwritten_suite(p: Profile) -> List[TestCase]:
    """The tests an integration engineer typically writes by hand.

    These are the happy paths and the one or two obvious error cases that appear
    in provider quickstarts: authorize then capture, authorize then void,
    authorize and let it expire, a partial capture, and a capture that asks for
    more than was authorized.
    """
    a = p.auth_amount
    over = a + p.over_capture_allowance + 1
    tests = [
        TestCase("auth_then_full_capture", [TestOp(AUTHORIZE, a), TestOp(CAPTURE, a, True)]),
        TestCase("auth_then_partial_capture", [TestOp(AUTHORIZE, a), TestOp(CAPTURE, max(1, a // 2), True)]),
        TestCase("auth_then_void", [TestOp(AUTHORIZE, a), TestOp(VOID)]),
        TestCase(
            "auth_then_expire",
            [TestOp(AUTHORIZE, a)] + [TestOp(ADVANCE_TIME, 1)] * (p.validity + p.max_release_delay),
        ),
        TestCase("capture_over_limit", [TestOp(AUTHORIZE, a), TestOp(CAPTURE, over, True)]),
        TestCase(
            "capture_then_capture_again",
            [TestOp(AUTHORIZE, a), TestOp(CAPTURE, 1, True), TestOp(CAPTURE, 1, True)],
        ),
        TestCase(
            "void_then_capture",
            [TestOp(AUTHORIZE, a), TestOp(VOID), TestOp(CAPTURE, 1, True)],
        ),
        TestCase("capture_without_auth", [TestOp(CAPTURE, a, True)]),
    ]
    if p.max_non_final_captures > 0:
        tests.append(
            TestCase(
                "two_partial_captures_then_final",
                [TestOp(AUTHORIZE, a), TestOp(CAPTURE, 1, False), TestOp(CAPTURE, 1, False),
                 TestOp(CAPTURE, 0, True)],
            )
        )
    if p.supports_incremental_auth:
        tests.append(
            TestCase(
                "increase_then_capture",
                [TestOp(AUTHORIZE, a), TestOp(INCREASE_AUTH, 1), TestOp(CAPTURE, a + 1, True)],
            )
        )
    return tests


def api_calls(tests: List[TestCase], include_negative: bool, p: Profile) -> int:
    """Total calls a suite makes, rejection checks included."""
    from .harness import rejecting_ops

    total = 0
    for t in tests:
        s = M.initial_state(p)
        for op in t.ops:
            if include_negative:
                total += len(rejecting_ops(p, s))
            total += 1
            _, s = step(p, s, op)
        if include_negative:
            total += len(rejecting_ops(p, s))
    return total
