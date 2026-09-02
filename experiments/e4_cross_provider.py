"""E4 -- where two providers implementing the same lifecycle disagree.

For each pair of provider profiles the search enumerates every call sequence on
which their documented behavior diverges, then collapses sequences that are the
same disagreement reached by different prefixes. What comes out is a short list
of independent divergences with an executable witness for each, plus the profile
field that explains it.

Both sides are put on a shared clock bound first. Without that, the profile with
the shorter horizon stops advancing sooner and the saturation would be reported
as a behavioral difference it is not.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from holdspec.differential import find_all_differences, group_differences  # noqa: E402
from holdspec.profiles import ALL_PROFILES, BY_NAME, DIFFERENTIAL_PAIRS    # noqa: E402
from holdspec.sut import ReferencePSP                                      # noqa: E402

RESULTS = REPO / "results"

COMPARED_FIELDS = [
    "over_capture_allowance",
    "max_non_final_captures",
    "supports_incremental_auth",
    "void_after_partial",
    "validity",
    "max_release_delay",
    "documented_validity_days",
    "documented_over_capture_pct",
    "documented_max_captures",
    "remainder_release_mechanism",
]


def field_deltas(a, b) -> dict:
    out = {}
    for f in COMPARED_FIELDS:
        va, vb = getattr(a, f), getattr(b, f)
        if va != vb:
            out[f] = {a.name: va, b.name: vb}
    return out


def compare(a, b) -> dict:
    horizon = max(a.horizon, b.horizon)
    a2 = dataclasses.replace(a, horizon_override=horizon)
    b2 = dataclasses.replace(b, horizon_override=horizon)
    ops = a2 if (a2.max_auth_amount + a2.over_capture_allowance) >= (
        b2.max_auth_amount + b2.over_capture_allowance
    ) else b2
    raw = find_all_differences(lambda: ReferencePSP(a2), lambda: ReferencePSP(b2), ops)
    grouped = group_differences(raw)
    return {
        "left": a.name,
        "right": b.name,
        "left_provider": a.provider,
        "right_provider": b.provider,
        "shared_horizon": horizon,
        "profile_field_deltas": field_deltas(a, b),
        "divergence_classes": len(grouped),
        "divergent_sequences": len(raw),
        "shortest_witness": grouped[0]["witness"] if grouped else None,
        "divergences": grouped,
    }


def main() -> int:
    highlighted = []
    for left, right in DIFFERENTIAL_PAIRS:
        row = compare(BY_NAME[left], BY_NAME[right])
        highlighted.append(row)
        print(f"{left:32s} vs {right:32s} classes={row['divergence_classes']:2d}")
        for d in row["divergences"]:
            amounts = ",".join(str(a) for a in d["amounts"])
            print(f"    [{d['field']:11s}] {d['op_kind']:14s} final={str(d['op_final']):5s} "
                  f"amounts={amounts:12s} witness: {d['witness']}")

    print("\nall pairs:")
    all_pairs = []
    for a, b in itertools.combinations(ALL_PROFILES, 2):
        row = compare(a, b)
        all_pairs.append(row)
        print(f"  {a.name:32s} vs {b.name:32s} classes={row['divergence_classes']:2d}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "e4_cross_provider.json").write_text(
        json.dumps({"highlighted_pairs": highlighted, "all_pairs": all_pairs}, indent=2) + "\n"
    )
    identical = [r for r in all_pairs if r["divergence_classes"] == 0]
    print(
        f"\npairs compared: {len(all_pairs)}, "
        f"pairs with no reachable difference: {len(identical)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
