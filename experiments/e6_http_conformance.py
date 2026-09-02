"""E6 -- the same suite, run black-box over HTTP.

E3 grades implementations in process. This one runs the identical suite against
a service over the network, in the provider's own API vocabulary, through the
adapters in holdspec.http_sut. Two things get checked that an in-process run
cannot: that the suite is genuinely black-box, and that the adapters translate
correctly -- an adapter that assumes Stripe's shape fits Adyen's fails here.

A defect is then injected into the service and the suite is run again, so the
detection claim is about a network service and not only about a Python object.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from holdspec.generator import model_suite            # noqa: E402
from holdspec.http_sut import AdyenShapedPSP, StripeShapedPSP  # noqa: E402
from holdspec.profiles import BY_NAME                 # noqa: E402
from holdspec.runner import run_suite                 # noqa: E402
from holdspec.store import export_corpus, open_store  # noqa: E402

RESULTS = REPO / "results"
APP = REPO / "docker" / "mock_psp" / "app.py"

# Which mock to stand up for each profile, and which adapter talks to it.
DEPLOYMENTS = [
    ("stripe_card_default", "stripe", StripeShapedPSP, 8081),
    ("stripe_multicapture", "stripe", StripeShapedPSP, 8082),
    ("adyen_card_default", "adyen", AdyenShapedPSP, 8083),
    ("adyen_multiple_partial_captures", "adyen", AdyenShapedPSP, 8084),
]

INJECTED_DEFECTS = ["M01_capture_after_close", "M03_unbounded_over_capture", "M07_no_release"]


def _wait(port: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/_test/profile", timeout=1).read()
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.15)
    raise RuntimeError(f"mock PSP on :{port} did not come up")


@contextmanager
def mock_psp(profile: str, api: str, port: int, defect: str = ""):
    env = dict(os.environ, MOCK_API=api, MOCK_PROFILE=profile,
               MOCK_PORT=str(port), MOCK_DEFECT=defect)
    proc = subprocess.Popen(
        [sys.executable, str(APP)], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        _wait(port)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()


def main() -> int:
    rows = []
    failures = 0
    store_cm = open_store()
    store = store_cm.__enter__()

    for profile_name, api, adapter, port in DEPLOYMENTS:
        profile = BY_NAME[profile_name]
        suite = model_suite(profile)

        with mock_psp(profile_name, api, port) as base:
            t0 = time.time()
            rep = run_suite(lambda: adapter(base, profile), profile, suite, "model")
            clean = rep.to_dict()
            clean["seconds"] = round(time.time() - t0, 1)
            store.record(rep, "http")
        conforms = rep.failed == 0
        failures += 0 if conforms else 1
        print(
            f"{profile_name:34s} via {adapter.name:18s} "
            f"tests={rep.tests:4d} calls={rep.api_calls:6d} "
            + ("conforms" if conforms else f"FAILS ({rep.failed})")
            + f"  ({clean['seconds']}s)"
        )
        if not conforms:
            v = rep.violations[0]
            print(f"    first violation [{v.kind}] expected {v.expected} got {v.actual}")
            print(f"    script: {v.script()}")

        injected = []
        for defect in INJECTED_DEFECTS:
            with mock_psp(profile_name, api, port, defect=defect) as base:
                rep_d = run_suite(
                    lambda: adapter(base, profile), profile, suite, "model", stop_after=1
                )
            store.record(rep_d, "http", defect)
            injected.append(
                {
                    "defect": defect,
                    "detected": rep_d.detected,
                    "witness": rep_d.violations[0].script() if rep_d.violations else None,
                }
            )
            print(f"    injected {defect:28s} detected={rep_d.detected}")

        rows.append(
            {
                "profile": profile_name,
                "api_shape": api,
                "adapter": adapter.name,
                "clean_run": clean,
                "conforms": conforms,
                "injected_defects": injected,
            }
        )

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "e6_http_conformance.json").write_text(json.dumps(rows, indent=2) + "\n")
    store_cm.__exit__(None, None, None)
    corpus = export_corpus(RESULTS / "defect_corpus.json")
    print(f"defect corpus: {corpus} reproducible violations recorded")
    print(f"\ndeployments: {len(rows)}, non-conforming: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
