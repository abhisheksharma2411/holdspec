"""Running a conformance suite against a system under test.

The oracle is holdspec.harness: before each call it asks the model whether a
conforming PSP must accept the call and what must be observable afterwards, then
compares that against what the system under test actually did. The first
disagreement fails the test and is reported with the call sequence that produced
it, so a failure is a reproducible script rather than a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from . import model as M
from .generator import TestCase
from .harness import ADVANCE_TIME, AUTHORIZE, CAPTURE, INCREASE_AUTH, VOID, TestOp, expectation, rejecting_ops
from .profiles import Profile
from .sut import SUT, Result


@dataclass
class Violation:
    test: str
    step: int
    op: str
    kind: str            # "accept" | "reject" | "observation" | "released"
    expected: str
    actual: str
    prefix: List[str] = field(default_factory=list)

    def script(self) -> str:
        return " ; ".join(self.prefix + [self.op])


@dataclass
class RunReport:
    sut: str
    profile: str
    suite: str
    tests: int
    api_calls: int
    passed: int
    failed: int
    violations: List[Violation] = field(default_factory=list)

    @property
    def detected(self) -> bool:
        return self.failed > 0

    def to_dict(self) -> dict:
        return {
            "sut": self.sut,
            "profile": self.profile,
            "suite": self.suite,
            "tests": self.tests,
            "api_calls": self.api_calls,
            "passed": self.passed,
            "failed": self.failed,
            "detected": self.detected,
            "violations": [
                {
                    "test": v.test, "step": v.step, "op": v.op, "kind": v.kind,
                    "expected": v.expected, "actual": v.actual, "script": v.script(),
                }
                for v in self.violations[:20]
            ],
            "violation_count": len(self.violations),
        }


def _invoke(sut: SUT, op: TestOp) -> Result:
    if op.kind == AUTHORIZE:
        return sut.authorize(op.amount)
    if op.kind == CAPTURE:
        return sut.capture(op.amount, op.final)
    if op.kind == VOID:
        return sut.void()
    if op.kind == INCREASE_AUTH:
        return sut.increase_auth(op.amount)
    if op.kind == ADVANCE_TIME:
        sut.advance_time(op.amount)
        return Result(True)
    raise ValueError(f"unknown call {op.kind}")


def run_suite(
    make_sut: Callable[[], SUT],
    profile: Profile,
    tests: List[TestCase],
    suite_name: str,
    include_negative: bool = True,
    stop_after: Optional[int] = None,
) -> RunReport:
    """Execute `tests` against a fresh system under test per test case."""
    report = RunReport(
        sut=getattr(make_sut(), "name", "sut"),
        profile=profile.name,
        suite=suite_name,
        tests=len(tests),
        api_calls=0,
        passed=0,
        failed=0,
    )

    for test in tests:
        sut = make_sut()
        sut.reset()
        state = M.initial_state(profile)
        prefix: List[str] = []
        failed_here = False

        for i, op in enumerate(test.ops):
            if include_negative:
                bad = _check_rejections(sut, profile, state, test.name, i, prefix, report)
                if bad and not failed_here:
                    failed_here = True
            exp, state = expectation(profile, state, op)
            res = _invoke(sut, op)
            report.api_calls += 1
            v = _compare(sut, res, exp, test.name, i, op, prefix)
            if v is not None:
                report.violations.append(v)
                failed_here = True
                break
            prefix.append(str(op))

        if include_negative and not failed_here:
            _check_rejections(sut, profile, state, test.name, len(test.ops), prefix, report)
            failed_here = any(v.test == test.name for v in report.violations)

        if failed_here:
            report.failed += 1
            if stop_after is not None and report.failed >= stop_after:
                break
        else:
            report.passed += 1

    return report


def _check_rejections(sut, profile, state, test_name, step_idx, prefix, report) -> bool:
    """Every call the model refuses must also be refused by the system."""
    found = False
    for op in rejecting_ops(profile, state):
        before = sut.observe()
        res = _invoke(sut, op)
        report.api_calls += 1
        if res.accepted:
            report.violations.append(
                Violation(
                    test=test_name, step=step_idx, op=str(op), kind="reject",
                    expected="rejected", actual="accepted", prefix=list(prefix),
                )
            )
            found = True
            break
        after = sut.observe()
        if after != before:
            report.violations.append(
                Violation(
                    test=test_name, step=step_idx, op=str(op), kind="observation",
                    expected=f"unchanged {before}", actual=str(after), prefix=list(prefix),
                )
            )
            found = True
            break
    return found


def _compare(sut, res: Result, exp, test_name, step_idx, op, prefix) -> Optional[Violation]:
    if res.accepted != exp.accepted:
        return Violation(
            test=test_name, step=step_idx, op=str(op), kind="accept",
            expected="accepted" if exp.accepted else "rejected",
            actual="accepted" if res.accepted else f"rejected({res.error})",
            prefix=list(prefix),
        )
    obs = sut.observe()
    if obs != exp.observation:
        return Violation(
            test=test_name, step=step_idx, op=str(op), kind="observation",
            expected=str(exp.observation), actual=str(obs), prefix=list(prefix),
        )
    rel = sut.released()
    if rel not in exp.released:
        return Violation(
            test=test_name, step=step_idx, op=str(op), kind="released",
            expected=f"released in {list(exp.released)}", actual=str(rel),
            prefix=list(prefix),
        )
    return None
