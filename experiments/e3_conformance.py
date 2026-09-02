"""E3 -- how much of a broken PSP does a conformance suite actually catch?

Twelve mutants, each breaking exactly one rule of the hold lifecycle, are graded
by three suites that all share the same oracle. What differs is only how the
call sequences are chosen:

  model         generated from the state machine: every reachable state, every
                accepted transition, and a rejection check at every state
  random        random call sequences, given the same API-call budget as the
                model suite; a second arm gets ten times that budget, to
                separate "chose the wrong calls" from "did not make enough"
  handwritten   the happy paths and obvious error cases a provider quickstart
                leads an engineer to write

A mutant no sequence can distinguish from the reference is reported as
equivalent within the model's bounds, established by exhaustive differential
search rather than assumed, and excluded from the detection rates.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from holdspec.differential import find_difference          # noqa: E402
from holdspec.generator import (api_calls, handwritten_suite, model_suite,  # noqa: E402
                                random_suite)
from holdspec.mutants import MUTANTS                        # noqa: E402
from holdspec.profiles import ALL_PROFILES                  # noqa: E402
from holdspec.runner import run_suite                       # noqa: E402
from holdspec.store import open_store                       # noqa: E402
from holdspec.sut import ReferencePSP                       # noqa: E402

RESULTS = REPO / "results"
SEED = 20260901


def main() -> int:
    per_profile = []
    store_cm = open_store()
    store = store_cm.__enter__()
    grand = {"model": [0, 0], "random": [0, 0], "random_10x": [0, 0], "handwritten": [0, 0]}
    self_check_failures = 0

    for profile in ALL_PROFILES:
        t0 = time.time()
        suites = {
            "model": (model_suite(profile), True),
            "handwritten": (handwritten_suite(profile), False),
        }
        budget = api_calls(suites["model"][0], True, profile)
        suites["random"] = (random_suite(profile, budget, SEED), True)
        suites["random_10x"] = (random_suite(profile, budget * 10, SEED + 1), True)

        # The reference must pass every suite; if it does not, a "detection"
        # elsewhere could be the suite being wrong rather than the mutant.
        self_check = {}
        for name, (tests, neg) in suites.items():
            rep = run_suite(lambda: ReferencePSP(profile), profile, tests, name, include_negative=neg)
            store.record(rep, "in_process")
            self_check[name] = rep.to_dict()
            if rep.failed:
                self_check_failures += 1
                print(f"  !! reference fails its own {name} suite on {profile.name}")

        mutant_rows = []
        for cls in MUTANTS:
            diff = find_difference(
                lambda cls=cls: cls(profile), lambda: ReferencePSP(profile), profile
            )
            equivalent = diff is None
            row = {
                "mutant": cls.name,
                "breaks": cls.breaks,
                "equivalent_within_bounds": equivalent,
                "shortest_witness": diff.to_dict() if diff else None,
                "detected": {},
            }
            for name, (tests, neg) in suites.items():
                rep = run_suite(
                    lambda cls=cls: cls(profile), profile, tests, name,
                    include_negative=neg, stop_after=1,
                )
                store.record(rep, "in_process", cls.name)
                row["detected"][name] = rep.detected
                row.setdefault("first_violation", {})[name] = (
                    rep.violations[0].script() if rep.violations else None
                )
                if not equivalent:
                    grand[name][1] += 1
                    if rep.detected:
                        grand[name][0] += 1
            mutant_rows.append(row)

        killable = [m for m in mutant_rows if not m["equivalent_within_bounds"]]
        rates = {
            name: (
                sum(1 for m in killable if m["detected"][name]) / len(killable)
                if killable else float("nan")
            )
            for name in suites
        }
        per_profile.append(
            {
                "profile": profile.name,
                "provider": profile.provider,
                "suites": {
                    name: {
                        "tests": len(tests),
                        "api_calls": api_calls(tests, neg, profile),
                        "negative_checks": neg,
                    }
                    for name, (tests, neg) in suites.items()
                },
                "reference_self_check": self_check,
                "mutants": mutant_rows,
                "killable_mutants": len(killable),
                "equivalent_mutants": len(mutant_rows) - len(killable),
                "detection_rate": rates,
                "seconds": round(time.time() - t0, 1),
            }
        )
        print(
            f"{profile.name:34s} killable={len(killable):2d} equiv={len(mutant_rows)-len(killable):2d} "
            f"model={rates['model']:.2f} random={rates['random']:.2f} "
            f"random10x={rates['random_10x']:.2f} handwritten={rates['handwritten']:.2f}"
            f"  ({time.time()-t0:.0f}s)"
        )

    overall = {k: (v[0] / v[1] if v[1] else float("nan")) for k, v in grand.items()}
    print(
        "\noverall detection over all profiles: "
        + ", ".join(f"{k}={v:.3f} ({grand[k][0]}/{grand[k][1]})" for k, v in overall.items())
    )

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "e3_conformance.json").write_text(
        json.dumps(
            {"seed": SEED, "per_profile": per_profile,
             "overall": {k: {"detected": v[0], "killable": v[1], "rate": overall[k]}
                         for k, v in grand.items()}},
            indent=2,
        )
        + "\n"
    )
    store_cm.__exit__(None, None, None)
    return 1 if self_check_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
