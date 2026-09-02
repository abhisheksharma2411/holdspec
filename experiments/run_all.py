"""Run every experiment in order and summarize what came out.

Order matters only in that E5 should run first: if the TLA+ module and the
Python model have drifted apart, nothing downstream means what it claims to.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

STEPS = [
    ("E5  model equivalence (TLA+ vs Python)", "e5_equivalence.py"),
    ("E1  model checking and state-space scaling", "e1_model_check.py"),
    ("E2  spec mutation: is the checking vacuous?", "e2_spec_mutation.py"),
    ("E3  conformance suites against 12 mutants", "e3_conformance.py"),
    ("E4  cross-provider divergences", "e4_cross_provider.py"),
    ("E6  the same suite over HTTP", "e6_http_conformance.py"),
]


def main() -> int:
    failures = []
    for title, script in STEPS:
        print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")
        start = time.time()
        proc = subprocess.run([sys.executable, str(REPO / "experiments" / script)])
        print(f"-- {script} finished in {time.time() - start:.1f}s (exit {proc.returncode})")
        if proc.returncode != 0:
            failures.append(script)

    print(f"\n{'=' * 72}")
    if failures:
        print("experiments reporting a problem: " + ", ".join(failures))
    else:
        print("all experiments completed and agreed with the specification")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
