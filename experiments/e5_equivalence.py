"""E5 -- the Python model and the TLA+ module reach the same states.

The paper leans on two artifacts that must agree: spec/HoldSpec.tla, which is
model-checked, and holdspec.model, which generates tests and grades systems
under test. If they drift, every conformance result is about a different machine
than the one that was verified. This experiment enumerates both state spaces and
compares them element by element.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from holdspec.dump import tlc_state_set          # noqa: E402
from holdspec.model import reachable             # noqa: E402
from holdspec.profiles import ALL_PROFILES       # noqa: E402
from holdspec.tlc import write_config            # noqa: E402

RESULTS = REPO / "results"


def main() -> int:
    rows = []
    failures = 0
    for profile in ALL_PROFILES:
        cfg = write_config(profile, REPO / "spec" / "profiles" / f"{profile.name}.cfg")
        tlc_states = tlc_state_set(profile, cfg, RESULTS / "tlc_dumps")
        py_states, _ = reachable(profile)

        only_tlc = tlc_states - py_states
        only_py = py_states - tlc_states
        agree = not only_tlc and not only_py
        failures += 0 if agree else 1

        rows.append(
            {
                "profile": profile.name,
                "tlc_states": len(tlc_states),
                "python_states": len(py_states),
                "only_in_tlc": len(only_tlc),
                "only_in_python": len(only_py),
                "identical": agree,
                "example_only_in_tlc": str(sorted(only_tlc)[0]) if only_tlc else None,
                "example_only_in_python": str(sorted(only_py)[0]) if only_py else None,
            }
        )
        mark = "=" if agree else "DIFFER"
        print(
            f"{profile.name:34s} TLC={len(tlc_states):5d} Python={len(py_states):5d} {mark}"
        )

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "e5_equivalence.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"\nprofiles compared: {len(rows)}, mismatched: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
