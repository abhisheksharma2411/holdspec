"""E2 -- is any of this checking vacuous?

A specification that satisfies its invariants because nothing interesting can
happen is worth very little. This experiment breaks one guard at a time in
spec/HoldSpec.tla, re-runs TLC, and records which property catches the change.
A property no mutation can falsify is either redundant or true by construction,
and the paper says so rather than counting it as a verified guarantee.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from holdspec.profiles import BY_NAME  # noqa: E402
from holdspec.tlc import INVARIANTS, PROPERTIES, run_tlc, write_config  # noqa: E402

RESULTS = REPO / "results"
SPEC = REPO / "spec" / "HoldSpec.tla"
MUT_DIR = REPO / "spec"


@dataclass
class SpecMutation:
    key: str
    description: str
    old: str
    new: str
    expects: str          # property expected to catch it
    profile: str = "stripe_multicapture"


MUTATIONS = [
    SpecMutation(
        "S01_capture_ignores_expiry",
        "a final capture no longer checks the authorization deadline",
        "CaptureFinal(c) ==\n    /\\ state = \"HELD\"\n    /\\ clock < expiresAt",
        "CaptureFinal(c) ==\n    /\\ state = \"HELD\"",
        "INV_NoCaptureAfterExpiry",
    ),
    SpecMutation(
        "S02_capture_ignores_ceiling",
        "a final capture no longer checks the profile's capture ceiling",
        "    /\\ (SupportsFinalCapture \\/ capturedTotal + c = authAmt)\n"
        "    /\\ capturedTotal + c =< CaptureLimit\n",
        "    /\\ (SupportsFinalCapture \\/ capturedTotal + c = authAmt)\n",
        "INV_CaptureWithinLimit",
    ),
    SpecMutation(
        "S03_release_twice",
        "the hold may be released again after it has already been released",
        "ReleaseHold ==\n    /\\ state = \"CLOSED\"\n    /\\ released = 0\n    /\\ released' = 1",
        "ReleaseHold ==\n    /\\ state = \"CLOSED\"\n    /\\ released < 2\n    /\\ released' = released + 1",
        "INV_ReleaseAtMostOnce",
    ),
    SpecMutation(
        "S04_release_while_open",
        "held funds may be released before the hold closes",
        "ReleaseHold ==\n    /\\ state = \"CLOSED\"\n    /\\ released = 0",
        "ReleaseHold ==\n    /\\ state \\in {\"HELD\", \"CLOSED\"}\n    /\\ released = 0",
        "INV_NoReleaseBeforeClose",
    ),
    SpecMutation(
        "S05_release_deadline_not_enforced",
        "time may pass while a release is overdue",
        "    /\\ ~ExpiryPending\n    /\\ (ReleasePending => clock + 1 =< releaseDue)\n",
        "    /\\ ~ExpiryPending\n",
        "INV_BoundedRelease",
    ),
    SpecMutation(
        "S06_non_final_budget_ignored",
        "the non-final capture budget is not enforced",
        "    /\\ captureCount < MaxNonFinalCaptures\n",
        "",
        "INV_CaptureCountWithinProfile",
    ),
    SpecMutation(
        "S07_close_forgets_captured_total",
        "closing a hold does not record what had been captured",
        "    /\\ capturedAtClose' = capturedTotal + c\n",
        "    /\\ capturedAtClose' = capturedTotal\n",
        "INV_NoCaptureAfterClose",
    ),
    SpecMutation(
        "S08_no_release_fairness",
        "nothing obliges the provider to ever release the funds",
        "    /\\ WF_vars(ReleaseHold)",
        "    /\\ TRUE",
        "LIVE_EventualRelease",
    ),
    SpecMutation(
        "S09_no_expiry_fairness",
        "nothing obliges the provider to ever expire a stale authorization",
        "    /\\ WF_vars(Expire)",
        "    /\\ TRUE",
        "LIVE_EventualClose",
    ),
    SpecMutation(
        "S10_no_authorize_fairness",
        "the hold need never be created",
        "    /\\ WF_vars(Authorize)",
        "    /\\ TRUE",
        "LIVE_Termination",
    ),
]


def build_mutant(mut: SpecMutation) -> Path:
    text = SPEC.read_text()
    if mut.old not in text:
        raise ValueError(f"{mut.key}: anchor text not found in HoldSpec.tla")
    module = f"HoldSpec{mut.key.split('_')[0]}"
    mutated = text.replace(mut.old, mut.new, 1)
    mutated = re.sub(r"MODULE HoldSpec\b", f"MODULE {module}", mutated, count=1)
    path = MUT_DIR / f"{module}.tla"
    path.write_text(mutated)
    return path


def main() -> int:
    rows = []
    for mut in MUTATIONS:
        path = build_mutant(mut)
        module = path.stem
        profile = BY_NAME[mut.profile]
        # Pass 1: everything enabled. TLC stops at the first property that fails,
        # so this says whether the mutation is caught at all, not by which one.
        cfg_all = write_config(profile, REPO / "spec" / "profiles" / f"{module}.cfg")
        res_all = run_tlc(module, cfg_all, profile.name)

        # Pass 2: only the property this mutation was aimed at, so the
        # attribution is exact rather than an artifact of config ordering.
        is_inv = mut.expects in INVARIANTS
        cfg_one = write_config(
            profile,
            REPO / "spec" / "profiles" / f"{module}_only.cfg",
            invariants=[mut.expects] if is_inv else [],
            properties=[] if is_inv else [mut.expects],
        )
        res_one = run_tlc(module, cfg_one, profile.name)
        caught_alone = res_one.violated == mut.expects

        rows.append(
            {
                "mutation": mut.key,
                "description": mut.description,
                "profile": mut.profile,
                "expected_property": mut.expects,
                "first_property_to_fail": res_all.violated,
                "violation_kind": res_all.violation_kind,
                "counterexample_length": res_all.trace_length,
                "caught_by_expected_property_alone": caught_alone,
                "caught_by_any_property": not res_all.ok,
                "seconds": round(res_all.seconds + res_one.seconds, 2),
            }
        )
        verdict = "caught" if caught_alone else "NOT CAUGHT by the intended property"
        print(
            f"{mut.key:34s} {mut.expects:32s} {verdict:38s} "
            f"(first to fail with all enabled: {res_all.violated})"
        )
        path.unlink()

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "e2_spec_mutation.json").write_text(json.dumps(rows, indent=2) + "\n")

    survivors = [r for r in rows if not r["caught_by_any_property"]]
    exact = [r for r in rows if r["caught_by_expected_property_alone"]]
    print(
        f"\nmutations: {len(rows)}, caught by the property they target: {len(exact)}, "
        f"undetected by every property: {len(survivors)}"
    )
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
