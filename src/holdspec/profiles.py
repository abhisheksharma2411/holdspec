"""Provider profiles: the capability vector a PSP exposes for the hold lifecycle.

A profile is the only thing that varies between providers in HoldSpec. The
abstract state machine (spec/HoldSpec.tla and holdspec.model) is identical for
every provider; the profile supplies the guards' parameters.

Every field carries a provenance string pointing at the public documentation it
was read from. Nothing here is inferred from a live API: no PSP sandbox
credentials were available for this work (see BLOCKERS.md), so the profiles
state what the providers *document*, and the conformance suite is what would be
pointed at a sandbox to check whether the documentation is met.

Two scales appear side by side:

  * documented scale -- real units (days, percent), quoted from the docs. Used
    in the cross-provider comparison and in the paper's tables.
  * model scale -- small integers used for model checking and test generation,
    chosen so the reachable state space stays enumerable. The ordering between
    providers is preserved (a provider documenting a longer validity window gets
    a larger tick budget), so divergences survive the rescaling; the absolute
    values do not carry meaning.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, Optional


@dataclass(frozen=True)
class Provenance:
    """Where a documented fact was read, so a reviewer can re-check it."""

    url: str
    quote: str
    retrieved: str = "2026-09-01"


@dataclass(frozen=True)
class Profile:
    """Capability vector for one provider configuration."""

    name: str
    provider: str
    # --- model-scale parameters (feed TLA+ constants and the Python model) ---
    auth_amount: int
    max_auth_amount: int
    over_capture_allowance: int
    max_non_final_captures: int
    supports_incremental_auth: bool
    supports_final_capture: bool
    void_after_partial: bool
    validity: int
    max_release_delay: int
    # --- documented scale (real units, for the comparison tables) ---
    documented_validity_days: float
    documented_over_capture_pct: float
    documented_max_captures: int
    # how the remainder is released after a partial capture
    remainder_release_mechanism: str
    provenance: Dict[str, Provenance] = field(default_factory=dict)
    # Comparing two profiles is only meaningful on a shared clock bound: with
    # different horizons, one implementation simply stops advancing sooner and
    # the saturation looks like a behavioral difference. Pair comparisons set
    # this to the larger of the two horizons.
    horizon_override: Optional[int] = None

    @property
    def horizon(self) -> int:
        """Clock bound: long enough to reach expiry and then the release deadline."""
        if self.horizon_override is not None:
            return self.horizon_override
        return self.validity + self.max_release_delay

    def tla_constants(self) -> Dict[str, object]:
        return {
            "AuthAmount": self.auth_amount,
            "MaxAuthAmount": self.max_auth_amount,
            "OverCaptureAllowance": self.over_capture_allowance,
            "MaxNonFinalCaptures": self.max_non_final_captures,
            "SupportsIncrementalAuth": self.supports_incremental_auth,
            "SupportsFinalCapture": self.supports_final_capture,
            "VoidAfterPartial": self.void_after_partial,
            "Validity": self.validity,
            "MaxReleaseDelay": self.max_release_delay,
            "Horizon": self.horizon,
        }

    def to_dict(self) -> dict:
        d = asdict(self)
        d["provenance"] = {k: asdict(v) for k, v in self.provenance.items()}
        d["horizon"] = self.horizon
        return d


# --- documentation quotes, kept verbatim -----------------------------------

_STRIPE_HOLD = "https://docs.stripe.com/payments/place-a-hold-on-a-payment-method"
_STRIPE_MULTI = "https://docs.stripe.com/payments/multicapture"
_STRIPE_OVER = "https://docs.stripe.com/payments/overcapture"
_ADYEN_CAPTURE = "https://docs.adyen.com/online-payments/capture/"
_ADYEN_VALIDITY = "https://docs.adyen.com/online-payments/adjust-authorisation/"

P_STRIPE_DEFAULT = Profile(
    name="stripe_card_default",
    provider="Stripe",
    auth_amount=4,
    max_auth_amount=4,
    over_capture_allowance=0,
    max_non_final_captures=0,
    supports_incremental_auth=False,
    supports_final_capture=True,
    void_after_partial=False,
    validity=3,
    max_release_delay=2,
    documented_validity_days=7.0,
    documented_over_capture_pct=0.0,
    documented_max_captures=1,
    remainder_release_mechanism="automatic on partial capture",
    provenance={
        "max_captures": Provenance(
            _STRIPE_HOLD,
            "you can only perform one capture on an authorized payment for most "
            "payments. If you partially capture a payment, you can't perform "
            "another capture for the difference.",
        ),
        "remainder": Provenance(
            _STRIPE_HOLD, "A partial capture automatically releases the remaining amount."
        ),
        "validity": Provenance(
            _STRIPE_HOLD,
            "Visa 7 days / Mastercard 7 days / American Express 7 days / "
            "Discover 7 days (customer-initiated, card-not-present)",
        ),
        "expiry": Provenance(
            _STRIPE_HOLD,
            "If the authorization expires before you capture the funds, the funds "
            "are released and the payment status changes to canceled.",
        ),
    },
)

P_STRIPE_MULTICAPTURE = Profile(
    name="stripe_multicapture",
    provider="Stripe",
    auth_amount=4,
    max_auth_amount=4,
    over_capture_allowance=0,
    max_non_final_captures=2,
    supports_incremental_auth=False,
    supports_final_capture=True,
    void_after_partial=False,
    validity=3,
    max_release_delay=2,
    documented_validity_days=7.0,
    documented_over_capture_pct=0.0,
    documented_max_captures=51,
    remainder_release_mechanism="zero-amount capture with final_capture=true",
    provenance={
        "max_captures": Provenance(
            _STRIPE_MULTI,
            "Stripe allows up to 50 non-final captures for a single PaymentIntent. "
            "You can then perform one additional final capture to complete the payment.",
        ),
        "capture_bound": Provenance(
            _STRIPE_MULTI,
            "Capture a PaymentIntent multiple times for a single authorization, "
            "up to the full amount of the PaymentIntent.",
        ),
        "remainder": Provenance(
            _STRIPE_MULTI,
            "If you performed at least one capture and want to release the remaining "
            "uncaptured funds, set the amount to 0 and set final_capture to true.",
        ),
        "close": Provenance(
            _STRIPE_MULTI,
            "The PaymentIntent remains in a requires_capture state until you [...] "
            "Set final_capture to true [...] or the authorization window expires. "
            "At this point, Stripe releases any remaining funds.",
        ),
    },
)

P_STRIPE_OVERCAPTURE = Profile(
    name="stripe_overcapture",
    provider="Stripe",
    auth_amount=4,
    max_auth_amount=4,
    over_capture_allowance=1,
    max_non_final_captures=0,
    supports_incremental_auth=False,
    supports_final_capture=True,
    void_after_partial=False,
    validity=3,
    max_release_delay=2,
    documented_validity_days=7.0,
    documented_over_capture_pct=15.0,
    documented_max_captures=1,
    remainder_release_mechanism="automatic on partial capture",
    provenance={
        "over_capture": Provenance(
            _STRIPE_OVER,
            "Overcapture allows you to capture with an amount that's higher than "
            "the authorized amount for a card payment.",
        ),
        "over_capture_limit": Provenance(
            _STRIPE_OVER,
            "Visa, Global, All other merchant categories: +15%. "
            "The maximum_amount_capturable field indicates the maximum amount "
            "capturable for the PaymentIntent.",
        ),
        "eligibility": Provenance(
            _STRIPE_OVER,
            "Only available with Visa, Mastercard, American Express, or Discover. "
            "Only eligible for online card payments.",
        ),
    },
)

P_ADYEN_DEFAULT = Profile(
    name="adyen_card_default",
    provider="Adyen",
    auth_amount=4,
    max_auth_amount=4,
    over_capture_allowance=0,
    max_non_final_captures=0,
    supports_incremental_auth=False,
    supports_final_capture=True,
    void_after_partial=False,
    validity=4,
    max_release_delay=2,
    documented_validity_days=10.0,
    documented_over_capture_pct=0.0,
    documented_max_captures=1,
    remainder_release_mechanism="automatic on partial capture",
    provenance={
        "capture_bound": Provenance(
            _ADYEN_CAPTURE,
            "This must be the same as or, in case of a partial capture, less than "
            "the authorized amount.",
        ),
        "remainder": Provenance(
            _ADYEN_CAPTURE,
            "Any unclaimed amount that is left over after partially capturing a "
            "payment is automatically cancelled.",
        ),
        "validity": Provenance(
            _ADYEN_VALIDITY,
            "Visa: card-not-present cardholder-initiated transactions: 10 days.",
        ),
    },
)

P_ADYEN_MULTIPLE_PARTIAL = Profile(
    name="adyen_multiple_partial_captures",
    provider="Adyen",
    auth_amount=4,
    max_auth_amount=4,
    over_capture_allowance=0,
    max_non_final_captures=2,
    supports_incremental_auth=False,
    supports_final_capture=False,
    void_after_partial=True,
    validity=4,
    max_release_delay=2,
    documented_validity_days=10.0,
    documented_over_capture_pct=0.0,
    documented_max_captures=-1,  # not documented as a fixed number
    remainder_release_mechanism="explicit cancel of the remaining amount",
    provenance={
        "remainder": Provenance(
            _ADYEN_CAPTURE,
            "The unclaimed amount after an initial partial capture is not "
            "automatically cancelled. This is useful in some businesses models "
            "such as an ecommerce site where capture takes place upon shipment.",
        ),
        "enablement": Provenance(
            _ADYEN_CAPTURE, "you need to contact our Support Team to enable this feature."
        ),
        "capture_bound": Provenance(
            _ADYEN_CAPTURE,
            "This must be the same as or, in case of a partial capture, less than "
            "the authorized amount.",
        ),
    },
)

# A profile no provider documents: used only to exercise the incremental
# authorization action in the model-checking study.
P_INCREMENTAL = Profile(
    name="incremental_auth",
    provider="synthetic",
    auth_amount=4,
    max_auth_amount=6,
    over_capture_allowance=0,
    max_non_final_captures=1,
    supports_incremental_auth=True,
    supports_final_capture=True,
    void_after_partial=True,
    validity=3,
    max_release_delay=2,
    documented_validity_days=7.0,
    documented_over_capture_pct=0.0,
    documented_max_captures=2,
    remainder_release_mechanism="explicit cancel of the remaining amount",
    provenance={},
)

ALL_PROFILES = [
    P_STRIPE_DEFAULT,
    P_STRIPE_MULTICAPTURE,
    P_STRIPE_OVERCAPTURE,
    P_ADYEN_DEFAULT,
    P_ADYEN_MULTIPLE_PARTIAL,
    P_INCREMENTAL,
]

BY_NAME = {p.name: p for p in ALL_PROFILES}

# The pairs compared in the cross-provider differential study.
DIFFERENTIAL_PAIRS = [
    ("stripe_card_default", "adyen_card_default"),
    ("stripe_multicapture", "adyen_multiple_partial_captures"),
    ("stripe_overcapture", "adyen_card_default"),
]
