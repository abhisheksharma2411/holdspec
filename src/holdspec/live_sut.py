"""Adapters for real PSP sandboxes.

These were written against the published API references but have not been run:
no Stripe or Adyen sandbox credentials were available for this work, which
BLOCKERS.md records. Nothing in the paper's results comes from them. They are
here so that a reader with test credentials can point the same suite at a live
sandbox without writing any test code, and so the claim that the suite is
sandbox-ready is something a reader can check rather than take on trust.

Two things a live run has to face that the mock does not:

  * Time. `advance_time` cannot fast-forward a real authorization. A live run
    either sleeps for the real validity window -- days -- or restricts itself to
    the tests that do not depend on expiry. `SKIP_TIME_TESTS` marks the latter.
  * Identity. A sandbox will not reuse one authorization across tests, so each
    test opens a new one; `reset` forgets the current handle rather than
    rewinding a shared object.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional, Tuple

from .model import Observation
from .profiles import Profile
from .sut import Result

SKIP_TIME_TESTS = True


class LiveSandboxUnavailable(RuntimeError):
    """Raised when the credentials a live adapter needs are not configured."""


def _call(method: str, url: str, headers: dict, body: Optional[bytes]) -> Tuple[int, dict]:
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return exc.code, {}


class StripeSandbox:
    """Stripe PaymentIntents in test mode.

    Reads STRIPE_SECRET_KEY. Manual capture is requested at creation, and
    multicapture and overcapture are requested with `if_available` so the
    profile under test is the one the account actually grants.
    """

    name = "stripe_sandbox"
    BASE = "https://api.stripe.com/v1"

    def __init__(self, profile: Profile):
        self.profile = profile
        self.key = os.environ.get("STRIPE_SECRET_KEY", "")
        if not self.key:
            raise LiveSandboxUnavailable("STRIPE_SECRET_KEY is not set")
        self.pi: Optional[str] = None
        self._created_at = 0.0

    def _post(self, path: str, form: dict) -> Tuple[int, dict]:
        body = urllib.parse.urlencode(form, doseq=True).encode()
        return _call(
            "POST", f"{self.BASE}{path}",
            {
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body,
        )

    def _get(self, path: str) -> Tuple[int, dict]:
        return _call("GET", f"{self.BASE}{path}", {"Authorization": f"Bearer {self.key}"}, None)

    def reset(self) -> None:
        self.pi = None

    def authorize(self, amount: int) -> Result:
        form = {
            "amount": max(amount, 50),          # sandbox minimum charge
            "currency": "usd",
            "payment_method": "pm_card_visa",
            "confirm": "true",
            "capture_method": "manual",
            "return_url": "https://example.com/return",
            "payment_method_options[card][request_multicapture]":
                "if_available" if self.profile.max_non_final_captures else "never",
            "payment_method_options[card][request_overcapture]":
                "if_available" if self.profile.over_capture_allowance else "never",
        }
        status, body = self._post("/payment_intents", form)
        if status >= 400:
            return Result(False, (body.get("error") or {}).get("code", "error"))
        self.pi = body["id"]
        self._created_at = time.time()
        return Result(True)

    def capture(self, amount: int, final: bool = True) -> Result:
        if self.pi is None:
            return Result(False, "no_payment_intent")
        form = {"amount_to_capture": amount, "final_capture": "true" if final else "false"}
        status, body = self._post(f"/payment_intents/{self.pi}/capture", form)
        if status >= 400:
            return Result(False, (body.get("error") or {}).get("code", "error"))
        return Result(True)

    def void(self) -> Result:
        if self.pi is None:
            return Result(False, "no_payment_intent")
        status, body = self._post(f"/payment_intents/{self.pi}/cancel", {})
        if status >= 400:
            return Result(False, (body.get("error") or {}).get("code", "error"))
        return Result(True)

    def increase_auth(self, delta: int) -> Result:
        if self.pi is None:
            return Result(False, "no_payment_intent")
        _, cur = self._get(f"/payment_intents/{self.pi}")
        status, body = self._post(
            f"/payment_intents/{self.pi}/increment_authorization",
            {"amount": int(cur.get("amount", 0)) + delta},
        )
        if status >= 400:
            return Result(False, (body.get("error") or {}).get("code", "error"))
        return Result(True)

    def advance_time(self, ticks: int) -> None:
        # A live authorization expires on the card network's clock; there is no
        # API to move it. Expiry-dependent tests are skipped against a sandbox.
        raise NotImplementedError(
            "a live authorization cannot be fast-forwarded; run with SKIP_TIME_TESTS"
        )

    def observe(self) -> Observation:
        if self.pi is None:
            return Observation(status="NONE", auth_amount=0, captured_total=0)
        _, b = self._get(f"/payment_intents/{self.pi}")
        status = {
            "requires_payment_method": "NONE",
            "requires_confirmation": "NONE",
            "requires_action": "NONE",
            "processing": "HELD",
            "requires_capture": "HELD",
            "succeeded": "CLOSED",
            "canceled": "CLOSED",
        }[b["status"]]
        return Observation(
            status=status,
            auth_amount=int(b.get("amount", 0)),
            captured_total=int(b.get("amount_received", 0)),
        )

    def released(self) -> int:
        """Stripe does not report the release of held funds as a counter.

        The nearest observable is the charge's `captured` flag, which turns true
        on a final capture or when the authorization is reversed. A live run
        should read the charge.captured event instead of polling; this returns
        the polled approximation.
        """
        if self.pi is None:
            return 0
        _, b = self._get(f"/payment_intents/{self.pi}?expand[]=latest_charge")
        charge = b.get("latest_charge") or {}
        return 1 if charge.get("captured") else 0


class AdyenSandbox:
    """Adyen Checkout in test mode.

    Reads ADYEN_API_KEY and ADYEN_MERCHANT_ACCOUNT. Manual capture and multiple
    partial captures are account settings, not request parameters, so the
    profile under test has to match how the test account is configured.
    """

    name = "adyen_sandbox"
    BASE = "https://checkout-test.adyen.com/v71"

    def __init__(self, profile: Profile):
        self.profile = profile
        self.key = os.environ.get("ADYEN_API_KEY", "")
        self.merchant = os.environ.get("ADYEN_MERCHANT_ACCOUNT", "")
        if not self.key or not self.merchant:
            raise LiveSandboxUnavailable(
                "ADYEN_API_KEY and ADYEN_MERCHANT_ACCOUNT are not set"
            )
        self.ref: Optional[str] = None
        self._captured = 0

    def _post(self, path: str, payload: dict) -> Tuple[int, dict]:
        return _call(
            "POST", f"{self.BASE}{path}",
            {"x-API-key": self.key, "Content-Type": "application/json"},
            json.dumps(payload).encode(),
        )

    def reset(self) -> None:
        self.ref = None
        self._captured = 0

    def authorize(self, amount: int) -> Result:
        status, body = self._post(
            "/payments",
            {
                "amount": {"currency": "EUR", "value": max(amount, 1)},
                "reference": f"holdspec-{int(time.time()*1000)}",
                "paymentMethod": {
                    "type": "scheme",
                    "encryptedCardNumber": "test_4111111111111111",
                    "encryptedExpiryMonth": "test_03",
                    "encryptedExpiryYear": "test_2030",
                    "encryptedSecurityCode": "test_737",
                },
                "merchantAccount": self.merchant,
                "returnUrl": "https://example.com/return",
            },
        )
        if status >= 400 or body.get("resultCode") != "Authorised":
            return Result(False, body.get("errorCode", body.get("resultCode", "error")))
        self.ref = body["pspReference"]
        return Result(True)

    def capture(self, amount: int, final: bool = True) -> Result:
        if self.ref is None:
            return Result(False, "no_payment")
        multi = self.profile.max_non_final_captures > 0
        if not final and not multi:
            return Result(False, "multicapture_unavailable")
        if amount == 0:
            if not final or self._captured == 0:
                return Result(False, "invalid_amount")
            return self.void()
        status, body = self._post(
            f"/payments/{self.ref}/captures",
            {
                "amount": {"currency": "EUR", "value": amount},
                "reference": f"cap-{int(time.time()*1000)}",
                "merchantAccount": self.merchant,
            },
        )
        if status >= 400:
            return Result(False, body.get("errorCode", "error"))
        self._captured += 1
        if final and multi:
            self.void()
        return Result(True)

    def void(self) -> Result:
        if self.ref is None:
            return Result(False, "no_payment")
        status, body = self._post(
            f"/payments/{self.ref}/cancels",
            {"reference": f"cxl-{int(time.time()*1000)}", "merchantAccount": self.merchant},
        )
        if status >= 400:
            return Result(False, body.get("errorCode", "error"))
        return Result(True)

    def increase_auth(self, delta: int) -> Result:
        if self.ref is None:
            return Result(False, "no_payment")
        status, body = self._post(
            f"/payments/{self.ref}/amountUpdates",
            {
                "amount": {"currency": "EUR", "value": self.profile.auth_amount + delta},
                "reference": f"adj-{int(time.time()*1000)}",
                "merchantAccount": self.merchant,
            },
        )
        if status >= 400:
            return Result(False, body.get("errorCode", "error"))
        return Result(True)

    def advance_time(self, ticks: int) -> None:
        raise NotImplementedError(
            "a live authorisation cannot be fast-forwarded; run with SKIP_TIME_TESTS"
        )

    def observe(self) -> Observation:
        raise NotImplementedError(
            "Adyen reports modification outcomes asynchronously by webhook; a live "
            "run must consume the notification stream rather than poll for state"
        )

    def released(self) -> int:
        raise NotImplementedError("see observe(): the outcome arrives by webhook")


LIVE_ADAPTERS = {"stripe": StripeSandbox, "adyen": AdyenSandbox}
