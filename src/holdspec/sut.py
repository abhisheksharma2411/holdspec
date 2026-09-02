"""Systems under test: the interface, a reference PSP, and its mutants.

The reference implementation deliberately does NOT call holdspec.model. It is
written in the idiom a PSP actually exposes -- a status string, an authorized
amount, a capturable amount, a received amount -- and an adapter translates that
back into the abstract observation the oracle compares against. Grading an
implementation against a model it is a copy of would prove nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol

from .model import Observation
from .profiles import Profile


@dataclass(frozen=True)
class Result:
    """Outcome of one API call."""

    accepted: bool
    error: Optional[str] = None


ACCEPTED = Result(True)


class SUT(Protocol):
    """The black-box surface a conformance test may use."""

    name: str

    def reset(self) -> None: ...
    def authorize(self, amount: int) -> Result: ...
    def capture(self, amount: int, final: bool) -> Result: ...
    def void(self) -> Result: ...
    def increase_auth(self, delta: int) -> Result: ...
    def advance_time(self, ticks: int) -> None: ...
    def observe(self) -> Observation:
        if self.status == "requires_payment_method":
            status = "NONE"
        elif self.status == "requires_capture":
            status = "HELD"
        else:
            status = "CLOSED"
        return Observation(
            status=status,
            auth_amount=self.amount,
            captured_total=self.amount_received,
        )

    def released(self) -> int: ...


class ReferencePSP:
    """A PSP that implements the profile's documented hold lifecycle.

    Internal vocabulary follows the provider APIs rather than the spec:

      status            requires_payment_method | requires_capture | succeeded | canceled
      amount            the authorized amount
      amount_capturable what is still available to capture
      amount_received   what has been captured
      hold_releases     how many times funds were released back to the cardholder
    """

    name = "reference"

    def __init__(self, profile: Profile):
        self.profile = profile
        self.reset()

    # -- lifecycle ---------------------------------------------------------

    def reset(self) -> None:
        p = self.profile
        self.status = "requires_payment_method"
        self.amount = 0
        self.amount_capturable = 0
        self.amount_received = 0
        self.captures: List[int] = []
        self.non_final_captures = 0
        self.clock = 0
        self.expires_at = p.horizon + 1
        self.release_due = p.horizon + 1
        self.hold_releases = 0
        self.closed_by = "-"
        self.last_capture_at = p.horizon + 1
        self.accepted_captures = 0

    # -- hooks the mutants override ---------------------------------------

    def _open(self) -> bool:
        return self.status == "requires_capture"

    def _not_expired(self) -> bool:
        return self.clock < self.expires_at

    def _capture_ceiling(self) -> int:
        return self.amount + self.profile.over_capture_allowance

    def _non_final_budget(self) -> int:
        return self.profile.max_non_final_captures

    def _release_now(self) -> None:
        self.hold_releases += 1

    def _release_deadline(self) -> int:
        return self.clock + self.profile.max_release_delay

    def _void_allowed_after_capture(self) -> bool:
        return self.profile.void_after_partial

    def _final_capture_supported(self) -> bool:
        return self.profile.supports_final_capture

    # -- API ---------------------------------------------------------------

    def authorize(self, amount: int) -> Result:
        if self.status != "requires_payment_method":
            return Result(False, "already_authorized")
        self.status = "requires_capture"
        self.amount = amount
        self.amount_capturable = amount
        self.expires_at = self.clock + self.profile.validity
        return ACCEPTED

    def capture(self, amount: int, final: bool = True) -> Result:
        if not self._open():
            return Result(False, "not_capturable")
        if not self._not_expired():
            return Result(False, "authorization_expired")
        if amount < 0:
            return Result(False, "invalid_amount")
        if amount == 0 and not self.captures:
            return Result(False, "invalid_amount")
        if self.amount_received + amount > self._capture_ceiling():
            return Result(False, "amount_exceeds_authorization")
        if not final and self.non_final_captures >= self._non_final_budget():
            return Result(False, "multicapture_unavailable")
        if not self._final_capture_supported():
            closes = self.amount_received + amount >= self.amount
            if final and not closes:
                return Result(False, "final_capture_unavailable")
            if not final and closes:
                return Result(False, "capture_would_close_hold")

        if amount > 0:
            self.captures.append(amount)
            self.amount_received += amount
            self.last_capture_at = self.clock
        self.amount_capturable = max(0, self.amount - self.amount_received)

        if final:
            self.status = "succeeded"
            self.closed_by = "CAPTURE"
            self.amount_capturable = 0
            self.release_due = self._release_deadline()
        else:
            self.non_final_captures += 1
        self.accepted_captures += 1
        return ACCEPTED

    def void(self) -> Result:
        if not self._open():
            return Result(False, "not_cancelable")
        if not self._not_expired():
            return Result(False, "authorization_expired")
        if self.amount_received > 0 and not self._void_allowed_after_capture():
            return Result(False, "cannot_cancel_after_capture")
        self.status = "canceled"
        self.closed_by = "VOID"
        self.amount_capturable = 0
        self.release_due = self._release_deadline()
        return ACCEPTED

    def increase_auth(self, delta: int) -> Result:
        if not self.profile.supports_incremental_auth:
            return Result(False, "not_supported")
        if not self._open():
            return Result(False, "not_adjustable")
        if not self._not_expired():
            return Result(False, "authorization_expired")
        if delta <= 0 or self.amount + delta > self.profile.max_auth_amount:
            return Result(False, "invalid_amount")
        self.amount += delta
        self.amount_capturable = max(0, self.amount - self.amount_received)
        return ACCEPTED

    def advance_time(self, ticks: int) -> None:
        for _ in range(ticks):
            if self.clock >= self.profile.horizon:
                break
            self.clock += 1
            self._on_tick()

    def _on_tick(self) -> None:
        if self._open() and self.clock >= self.expires_at:
            self.status = "canceled"
            self.closed_by = "EXPIRY"
            self.amount_capturable = 0
            self.release_due = self._release_deadline()
        if self._closed() and self.hold_releases == 0 and self.clock >= self.release_due:
            self._release_now()

    def _closed(self) -> bool:
        return self.status in ("succeeded", "canceled")

    # -- black-box view ----------------------------------------------------

    def observe(self) -> Observation:
        if self.status == "requires_payment_method":
            status = "NONE"
        elif self.status == "requires_capture":
            status = "HELD"
        else:
            status = "CLOSED"
        return Observation(
            status=status,
            auth_amount=self.amount,
            captured_total=self.amount_received,
        )

    def released(self) -> int:
        return self.hold_releases
