"""Mutation operators: PSP implementations that each break one lifecycle rule.

Each mutant corresponds to a defect that has a name in practice -- capture
accepted after a void, an over-capture bound that is not enforced, held funds
released twice, an expiry check that is off by one tick. They exist so the
detection power of a conformance suite can be measured rather than asserted.

Every mutant overrides one hook on ReferencePSP, so the difference between a
correct provider and a broken one is a single decision, not a rewrite.
"""

from __future__ import annotations

from typing import Dict, List, Type

from .profiles import Profile
from .sut import ReferencePSP, Result


class M01CaptureAfterClose(ReferencePSP):
    """Accepts a capture once the hold has closed (void, expiry, final capture)."""

    name = "M01_capture_after_close"
    breaks = "INV_NoCaptureAfterClose"

    def _open(self) -> bool:
        return self.status != "requires_payment_method"


class M02CaptureAfterExpiry(ReferencePSP):
    """Never checks the authorization deadline before capturing."""

    name = "M02_capture_after_expiry"
    breaks = "INV_NoCaptureAfterExpiry"

    def _not_expired(self) -> bool:
        return True


class M03UnboundedOverCapture(ReferencePSP):
    """Does not enforce any ceiling on the captured total."""

    name = "M03_unbounded_over_capture"
    breaks = "INV_CaptureWithinLimit"

    def _capture_ceiling(self) -> int:
        return 10 ** 6


class M04CeilingOffByOne(ReferencePSP):
    """Allows one minor unit more than the profile permits."""

    name = "M04_ceiling_off_by_one"
    breaks = "INV_CaptureWithinLimit"

    def _capture_ceiling(self) -> int:
        return super()._capture_ceiling() + 1


class M05ExtraNonFinalCapture(ReferencePSP):
    """Grants one more non-final capture than the profile documents."""

    name = "M05_extra_non_final_capture"
    breaks = "INV_CaptureCountWithinProfile"

    def _non_final_budget(self) -> int:
        return super()._non_final_budget() + 1


class M06DoubleRelease(ReferencePSP):
    """Releases the held funds twice."""

    name = "M06_double_release"
    breaks = "INV_ReleaseAtMostOnce"

    def _release_now(self) -> None:
        self.hold_releases += 2


class M07NoRelease(ReferencePSP):
    """Closes the hold but never gives the money back."""

    name = "M07_no_release"
    breaks = "INV_BoundedRelease"

    def _release_now(self) -> None:
        pass


class M08LateRelease(ReferencePSP):
    """Releases held funds, but after the deadline the profile allows."""

    name = "M08_late_release"
    breaks = "INV_BoundedRelease"

    def _release_deadline(self) -> int:
        return self.clock + self.profile.max_release_delay + 2


class M09VoidAfterPartial(ReferencePSP):
    """Accepts a void after a capture even when the profile forbids it."""

    name = "M09_void_after_partial"
    breaks = "profile Void guard"

    def _void_allowed_after_capture(self) -> bool:
        return True


class M10PartialCaptureKeepsHold(ReferencePSP):
    """Leaves the remainder on hold after a partial capture that should close it."""

    name = "M10_partial_capture_keeps_hold"
    breaks = "INV_HoldFullyReleased"

    def capture(self, amount: int, final: bool = True) -> Result:
        if final and 0 < amount < self.amount - self.amount_received:
            return super().capture(amount, final=False)
        return super().capture(amount, final)


class M11ExpireOneTickLate(ReferencePSP):
    """Treats the expiry instant as still inside the validity window."""

    name = "M11_expire_one_tick_late"
    breaks = "INV_NoCaptureAfterExpiry"

    def _not_expired(self) -> bool:
        return self.clock <= self.expires_at

    def _on_tick(self) -> None:
        if self._open() and self.clock > self.expires_at:
            self.status = "canceled"
            self.closed_by = "EXPIRY"
            self.amount_capturable = 0
            self.release_due = self._release_deadline()
        if self._closed() and self.hold_releases == 0 and self.clock >= self.release_due:
            self._release_now()


class M12ReleaseBeforeClose(ReferencePSP):
    """Releases the hold while the authorization is still open."""

    name = "M12_release_before_close"
    breaks = "INV_NoReleaseBeforeClose"

    def _on_tick(self) -> None:
        if self._open() and self.hold_releases == 0 and self.clock >= 1:
            self._release_now()
        super()._on_tick()


MUTANTS: List[Type[ReferencePSP]] = [
    M01CaptureAfterClose,
    M02CaptureAfterExpiry,
    M03UnboundedOverCapture,
    M04CeilingOffByOne,
    M05ExtraNonFinalCapture,
    M06DoubleRelease,
    M07NoRelease,
    M08LateRelease,
    M09VoidAfterPartial,
    M10PartialCaptureKeepsHold,
    M11ExpireOneTickLate,
    M12ReleaseBeforeClose,
]

BY_NAME: Dict[str, Type[ReferencePSP]] = {m.name: m for m in MUTANTS}


def build(cls: Type[ReferencePSP], profile: Profile) -> ReferencePSP:
    return cls(profile)
