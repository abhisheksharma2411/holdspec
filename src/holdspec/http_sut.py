"""HTTP adapters: one conformance suite, two provider API shapes.

Each adapter turns the suite's abstract calls into the requests a provider
documents, and turns the provider's response back into the abstract observation
the oracle understands. The suite does not know which provider it is talking to.

The translation is where the two APIs stop lining up, and the mismatch is not
cosmetic. Releasing the remainder after a partial capture is a capture on
Stripe -- amount zero with final_capture true -- and a cancel on Adyen. An
adapter that assumes one shape fits both silently does the wrong thing on the
other, which is the divergence E4 finds and this module has to absorb.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Optional, Tuple

from .model import Observation
from .profiles import Profile
from .sut import Result

_TIMEOUT = 10


def _request(method: str, url: str, payload: Optional[dict] = None) -> Tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = resp.read()
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body) if body else {}
        except json.JSONDecodeError:
            return exc.code, {}


class HttpPSP:
    """Base adapter: the control plane both mock shapes share."""

    name = "http"

    def __init__(self, base_url: str, profile: Profile):
        self.base = base_url.rstrip("/")
        self.profile = profile
        self.reset()

    def reset(self) -> None:
        _request("POST", f"{self.base}/_test/reset")

    def advance_time(self, ticks: int) -> None:
        _request("POST", f"{self.base}/_test/clock", {"ticks": ticks})

    def released(self) -> int:
        _, body = _request("GET", f"{self.base}/_test/hold")
        return int(body.get("releases", 0))


class StripeShapedPSP(HttpPSP):
    """Speaks the Stripe PaymentIntents shape."""

    name = "http_stripe_shaped"
    HOLD = "pi_holdspec_1"

    def _pi(self, suffix: str = "") -> str:
        return f"{self.base}/v1/payment_intents/{self.HOLD}{suffix}"

    def _result(self, status: int, body: dict) -> Result:
        if status < 400:
            return Result(True)
        return Result(False, (body.get("error") or {}).get("code", "error"))

    def authorize(self, amount: int) -> Result:
        s, b = _request("POST", f"{self.base}/v1/payment_intents",
                        {"amount": amount, "capture_method": "manual"})
        return self._result(s, b)

    def capture(self, amount: int, final: bool = True) -> Result:
        s, b = _request("POST", self._pi("/capture"),
                        {"amount_to_capture": amount, "final_capture": final})
        return self._result(s, b)

    def void(self) -> Result:
        s, b = _request("POST", self._pi("/cancel"))
        return self._result(s, b)

    def increase_auth(self, delta: int) -> Result:
        _, cur = _request("GET", self._pi())
        s, b = _request("POST", self._pi("/increment_authorization"),
                        {"amount": int(cur.get("amount", 0)) + delta})
        return self._result(s, b)

    def observe(self) -> Observation:
        _, b = _request("GET", self._pi())
        status = {
            "requires_payment_method": "NONE",
            "requires_capture": "HELD",
            "succeeded": "CLOSED",
            "canceled": "CLOSED",
        }[b["status"]]
        return Observation(
            status=status,
            auth_amount=int(b.get("amount", 0)),
            captured_total=int(b.get("amount_received", 0)),
        )


class AdyenShapedPSP(HttpPSP):
    """Speaks the Adyen payments/modifications shape.

    Adyen has no final-capture flag. Whether a partial capture leaves the
    remainder on hold is an account-level setting, so the adapter reads it from
    the profile: when multiple partial captures are enabled, a final capture is
    a capture followed by an explicit cancel of what is left, and releasing the
    remainder without capturing anything is a bare cancel.
    """

    name = "http_adyen_shaped"
    HOLD = "psp_holdspec_1"

    def reset(self) -> None:
        super().reset()
        self._captures = 0

    def _p(self, suffix: str = "") -> str:
        return f"{self.base}/payments/{self.HOLD}{suffix}"

    def _result(self, status: int, body: dict) -> Result:
        if status < 400:
            return Result(True)
        return Result(False, body.get("errorCode", "error"))

    def authorize(self, amount: int) -> Result:
        s, b = _request("POST", f"{self.base}/payments",
                        {"amount": {"value": amount, "currency": "EUR"}})
        return self._result(s, b)

    def capture(self, amount: int, final: bool = True) -> Result:
        multi = self.profile.max_non_final_captures > 0
        if not final and not multi:
            # There is no non-final capture to request: on this account the
            # remainder is always released, so the call cannot be expressed.
            return Result(False, "multicapture_unavailable")
        if multi and not self.profile.supports_final_capture:
            # No final-capture flag exists on this account, so one request has
            # to serve two abstract operations. A capture that takes the whole
            # authorised amount ends the hold; one that leaves a remainder keeps
            # it open. Whichever of the two the caller asked for and the amount
            # does not deliver is simply not expressible here.
            _, cur = _request("GET", self._p())
            authorised = int((cur.get("amount") or {}).get("value", 0))
            captured = int((cur.get("capturedAmount") or {}).get("value", 0))
            closes = captured + amount >= authorised
            if final and not closes:
                return Result(False, "final_capture_unavailable")
            if not final and closes:
                return Result(False, "capture_would_close_hold")
        if amount == 0:
            if not final or self._captures == 0:
                return Result(False, "invalid_amount")
            return self._result(*_request("POST", self._p("/cancels")))
        s, b = _request("POST", self._p("/captures"),
                        {"amount": {"value": amount, "currency": "EUR"}})
        res = self._result(s, b)
        if res.accepted:
            self._captures += 1
            if final and multi:
                _request("POST", self._p("/cancels"))
        return res

    def void(self) -> Result:
        s, b = _request("POST", self._p("/cancels"))
        return self._result(s, b)

    def increase_auth(self, delta: int) -> Result:
        _, cur = _request("GET", self._p())
        current = int((cur.get("amount") or {}).get("value", 0))
        s, b = _request("POST", self._p("/amountUpdates"),
                        {"amount": {"value": current + delta, "currency": "EUR"}})
        return self._result(s, b)

    def observe(self) -> Observation:
        _, b = _request("GET", self._p())
        status = {"Empty": "NONE", "Authorised": "HELD",
                  "Settled": "CLOSED", "Cancelled": "CLOSED"}[b["status"]]
        return Observation(
            status=status,
            auth_amount=int((b.get("amount") or {}).get("value", 0)),
            captured_total=int((b.get("capturedAmount") or {}).get("value", 0)),
        )


ADAPTERS = {"stripe": StripeShapedPSP, "adyen": AdyenShapedPSP}
