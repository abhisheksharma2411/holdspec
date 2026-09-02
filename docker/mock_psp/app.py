"""A mock PSP that speaks a real provider's API shape over HTTP.

The point of this service is to make the conformance suite genuinely black-box:
the suite talks to it over the network, in the provider's own vocabulary, with
no access to the object it is testing. Swapping in a live sandbox is then a
change of base URL and credentials, not a change of test.

Two API shapes are served, selected by MOCK_API:

  stripe   POST /v1/payment_intents
           POST /v1/payment_intents/{id}/capture   {amount_to_capture, final_capture}
           POST /v1/payment_intents/{id}/cancel
           GET  /v1/payment_intents/{id}

  adyen    POST /payments
           POST /payments/{ref}/captures           {amount:{value}}
           POST /payments/{ref}/cancels
           GET  /payments/{ref}

Both also expose a control plane the suite needs and a live PSP does not:

  POST /_test/clock    {"ticks": n}    advance the simulated clock
  POST /_test/reset                    start a fresh hold
  GET  /_test/hold                     the hold's release counter

MOCK_PROFILE picks the provider profile; MOCK_DEFECT optionally loads one of the
mutants from holdspec.mutants, which is how the harness checks that a defect
really is visible from outside the process.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from holdspec.mutants import BY_NAME as MUTANTS_BY_NAME  # noqa: E402
from holdspec.profiles import BY_NAME as PROFILES        # noqa: E402
from holdspec.sut import ReferencePSP                    # noqa: E402

API = os.environ.get("MOCK_API", "stripe")
PROFILE = PROFILES[os.environ.get("MOCK_PROFILE", "stripe_card_default")]
DEFECT = os.environ.get("MOCK_DEFECT", "")
PORT = int(os.environ.get("MOCK_PORT", "8080"))

HOLD_ID = "pi_holdspec_1" if API == "stripe" else "psp_holdspec_1"


def new_psp():
    cls = MUTANTS_BY_NAME[DEFECT] if DEFECT else ReferencePSP
    return cls(PROFILE)


STATE = {"psp": new_psp()}


def stripe_view(psp) -> dict:
    return {
        "id": HOLD_ID,
        "object": "payment_intent",
        "status": psp.status,
        "amount": psp.amount,
        "amount_capturable": psp.amount_capturable,
        "amount_received": psp.amount_received,
        "capture_count": psp.accepted_captures,
        "closed_by": psp.closed_by,
    }


def adyen_view(psp) -> dict:
    status = {
        "requires_payment_method": "Empty",
        "requires_capture": "Authorised",
        "succeeded": "Settled",
        "canceled": "Cancelled",
    }[psp.status]
    return {
        "pspReference": HOLD_ID,
        "status": status,
        "amount": {"value": psp.amount, "currency": "EUR"},
        "capturedAmount": {"value": psp.amount_received, "currency": "EUR"},
        "captureCount": psp.accepted_captures,
        "closedBy": psp.closed_by,
    }


def view(psp) -> dict:
    return stripe_view(psp) if API == "stripe" else adyen_view(psp)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep the test output readable
        pass

    # -- plumbing ---------------------------------------------------------

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code: int, message: str) -> None:
        if API == "stripe":
            self._send(code, {"error": {"code": message, "type": "invalid_request_error"}})
        else:
            self._send(code, {"errorCode": message, "message": message, "status": code})

    # -- routes -----------------------------------------------------------

    def do_GET(self):  # noqa: N802
        psp = STATE["psp"]
        if self.path == "/_test/hold":
            return self._send(200, {"releases": psp.released(), "clock": psp.clock})
        if self.path == "/_test/profile":
            return self._send(200, {"profile": PROFILE.name, "api": API, "defect": DEFECT})
        if self.path.rstrip("/").endswith(HOLD_ID):
            return self._send(200, view(psp))
        return self._error(404, "not_found")

    def do_POST(self):  # noqa: N802
        psp = STATE["psp"]
        body = self._body()
        path = self.path.rstrip("/")

        if path == "/_test/reset":
            STATE["psp"] = new_psp()
            return self._send(200, {"reset": True})
        if path == "/_test/clock":
            psp.advance_time(int(body.get("ticks", 1)))
            return self._send(200, {"clock": psp.clock, "releases": psp.released()})

        if API == "stripe":
            return self._stripe(path, body, psp)
        return self._adyen(path, body, psp)

    def _stripe(self, path, body, psp):
        if path == "/v1/payment_intents":
            res = psp.authorize(int(body.get("amount", 0)))
            return self._send(200, view(psp)) if res.accepted else self._error(400, res.error)
        if path == f"/v1/payment_intents/{HOLD_ID}/capture":
            amount = body.get("amount_to_capture")
            amount = psp.amount_capturable if amount is None else int(amount)
            final = bool(body.get("final_capture", True))
            res = psp.capture(amount, final)
            return self._send(200, view(psp)) if res.accepted else self._error(400, res.error)
        if path == f"/v1/payment_intents/{HOLD_ID}/cancel":
            res = psp.void()
            return self._send(200, view(psp)) if res.accepted else self._error(400, res.error)
        if path == f"/v1/payment_intents/{HOLD_ID}/increment_authorization":
            res = psp.increase_auth(int(body.get("amount", 0)) - psp.amount)
            return self._send(200, view(psp)) if res.accepted else self._error(400, res.error)
        return self._error(404, "not_found")

    def _adyen(self, path, body, psp):
        if path == "/payments":
            res = psp.authorize(int(body.get("amount", {}).get("value", 0)))
            return self._send(200, view(psp)) if res.accepted else self._error(422, res.error)
        if path == f"/payments/{HOLD_ID}/captures":
            amount = int(body.get("amount", {}).get("value", 0))
            # Adyen has no final-capture flag. On a single-partial-capture
            # account any capture releases the remainder, so it closes the hold;
            # with multiple partial captures enabled a capture closes the hold
            # only when it takes the whole authorised amount.
            final = (PROFILE.max_non_final_captures == 0
                     or psp.amount_received + amount >= psp.amount)
            res = psp.capture(amount, final)
            return self._send(201, view(psp)) if res.accepted else self._error(422, res.error)
        if path == f"/payments/{HOLD_ID}/cancels":
            res = psp.void()
            return self._send(201, view(psp)) if res.accepted else self._error(422, res.error)
        if path == f"/payments/{HOLD_ID}/amountUpdates":
            res = psp.increase_auth(int(body.get("amount", {}).get("value", 0)) - psp.amount)
            return self._send(201, view(psp)) if res.accepted else self._error(422, res.error)
        return self._error(404, "not_found")


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"mock {API} PSP on :{PORT} profile={PROFILE.name} defect={DEFECT or 'none'}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
