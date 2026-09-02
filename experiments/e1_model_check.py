"""E1 -- model-check every provider profile, then measure how the state space grows.

Part 1 runs TLC over spec/HoldSpec.tla for each profile with all eight safety
invariants and the three liveness properties enabled, and records the state
counts, the search depth, and the wall-clock time.

Part 2 varies one profile bound at a time -- the non-final capture budget and
the validity window -- to show how the reachable space scales, which is what
sets the practical limit on exhaustive checking.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from holdspec.profiles import ALL_PROFILES, P_STRIPE_MULTICAPTURE  # noqa: E402
from holdspec.tlc import INVARIANTS, PROPERTIES, run_tlc, write_config  # noqa: E402

RESULTS = REPO / "results"
CFG_DIR = REPO / "spec" / "profiles"


def check_profiles() -> list:
    rows = []
    for profile in ALL_PROFILES:
        cfg = write_config(profile, CFG_DIR / f"{profile.name}.cfg")
        res = run_tlc("HoldSpec", cfg, profile.name)
        row = res.to_dict()
        row.pop("stdout_tail")
        row["provider"] = profile.provider
        row["invariants_checked"] = len(INVARIANTS)
        row["properties_checked"] = len(PROPERTIES)
        row["constants"] = profile.tla_constants()
        rows.append(row)
        print(
            f"{profile.name:34s} ok={res.ok!s:5s} states={res.states_generated:7d} "
            f"distinct={res.distinct_states:7d} depth={res.diameter:3d} {res.seconds:6.2f}s"
            + ("" if res.ok else f"  VIOLATED {res.violated}")
        )
    return rows


def scaling_study() -> list:
    """How the reachable space grows with the profile's bounds."""
    rows = []
    base = P_STRIPE_MULTICAPTURE
    for field, values in (("max_non_final_captures", [0, 1, 2, 3, 4]),
                          ("validity", [2, 3, 4, 5, 6])):
        for value in values:
            profile = dataclasses.replace(base, name=f"scale_{field}_{value}", **{field: value})
            cfg = write_config(profile, CFG_DIR / f"{profile.name}.cfg")
            res = run_tlc("HoldSpec", cfg, profile.name)
            rows.append(
                {
                    "varied": field,
                    "value": value,
                    "states_generated": res.states_generated,
                    "distinct_states": res.distinct_states,
                    "diameter": res.diameter,
                    "seconds": res.seconds,
                    "ok": res.ok,
                }
            )
            print(f"  {field}={value:2d} distinct={res.distinct_states:8d} depth={res.diameter:3d} {res.seconds:6.2f}s")
    return rows


def main() -> int:
    print("== E1a: model checking each provider profile ==")
    profiles = check_profiles()
    print("\n== E1b: state-space scaling ==")
    scaling = scaling_study()

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "e1_model_check.json").write_text(
        json.dumps({"profiles": profiles, "scaling": scaling}, indent=2) + "\n"
    )
    failed = [r for r in profiles if not r["ok"]]
    print(f"\nprofiles checked: {len(profiles)}, failing: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
