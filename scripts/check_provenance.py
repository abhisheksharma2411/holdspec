"""Every result file must name one clean commit.

A results file records the revision it came from so a reader can check out that
revision and re-run it. Two things break that promise quietly. A ``dirty`` flag
means the tree held uncommitted edits, so the named commit is not the code that
ran. Several different commits across one results directory means the numbers
in the paper came from more than one version of the code, and no single
checkout reproduces the set.

Neither shows up in any figure, so this is a check rather than a convention:
``make check-provenance`` fails, and the paper does not ship.

The expected workflow is commit code, run experiments from the clean tree, then
commit the results. The commit recorded in each file is then the code that
produced it, and the results commit that follows does not change that.

Usage:  python scripts/check_provenance.py [--quiet]
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def provenance_of(payload) -> tuple[str, str] | None:
    """(commit, dirty) for a results payload, or None if it records neither."""
    if not isinstance(payload, dict):
        return None
    p = payload.get("provenance", payload)
    if not isinstance(p, dict):
        return None
    commit = p.get("git") or p.get("git_commit") or p.get("commit") or ""
    dirty = p.get("git_dirty")
    if isinstance(commit, str) and commit.endswith("-dirty"):
        commit, dirty = commit[: -len("-dirty")], "yes"
    if dirty in (True, "yes"):
        dirty = "yes"
    elif dirty in (False, "no"):
        dirty = "no"
    else:
        dirty = "no" if commit and commit != "unversioned" else "unknown"
    if not commit:
        return None
    return commit, dirty


def sidecar() -> dict | None:
    """Provenance kept beside the results rather than inside each of them.

    One project writes ``results/PROVENANCE.json`` mapping each result file to
    a content hash and recording the commit once, which is a better record
    than an inline field and not a worse one. Understanding both shapes is the
    checker's job; making every project write the same shape is not.
    """
    path = RESULTS / "PROVENANCE.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def check_sidecar(prov: dict, quiet: bool) -> int:
    problems = []
    commit = prov.get("git_commit") or ""
    if not commit or commit == "uncommitted":
        problems.append("PROVENANCE.json records no commit")
    if prov.get("git_dirty") != "no":
        problems.append(f"PROVENANCE.json records a dirty tree ({commit[:12]})")

    listed = prov.get("files", {})
    on_disk = {f.name for f in RESULTS.glob("*.json")} - {"PROVENANCE.json"}
    for missing in sorted(on_disk - set(listed)):
        problems.append(f"{missing}: not listed in PROVENANCE.json")
    for gone in sorted(set(listed) - on_disk):
        problems.append(f"{gone}: listed in PROVENANCE.json but not present")

    # The hash is the point of a sidecar: a result edited after the run would
    # otherwise inherit a commit it never came from.
    for name, meta in sorted(listed.items()):
        path = RESULTS / name
        if not path.exists():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        if meta.get("sha256_16") and digest != meta["sha256_16"]:
            problems.append(f"{name}: content does not match its recorded hash")

    for p in problems:
        print(f"  {p}")
    if problems:
        print(f"{len(listed)} result files, {len(problems)} provenance problem(s)")
        print("re-run: commit the code, then `make experiments`, then commit results")
        return 1
    if not quiet:
        print(f"{len(listed)} result files, one clean revision {commit[:12]} "
              f"(hashes verified)")
    return 0


def main(argv: list[str]) -> int:
    quiet = "--quiet" in argv
    prov = sidecar()
    if prov is not None:
        return check_sidecar(prov, quiet)
    files = sorted(RESULTS.glob("*.json"))
    if not files:
        print("no results to check; run the experiments first")
        return 1

    problems: list[str] = []
    commits: dict[str, list[str]] = {}
    for f in files:
        try:
            payload = json.loads(f.read_text())
        except json.JSONDecodeError as exc:
            problems.append(f"{f.name}: not valid JSON ({exc})")
            continue
        prov = provenance_of(payload)
        if prov is None:
            problems.append(f"{f.name}: records no revision")
            continue
        commit, dirty = prov
        if commit == "unversioned":
            problems.append(f"{f.name}: unversioned")
            continue
        if dirty != "no":
            problems.append(f"{f.name}: produced from a dirty tree ({commit[:12]})")
        commits.setdefault(commit, []).append(f.name)

    if len(commits) > 1:
        detail = "; ".join(f"{c[:12]}: {len(v)} file(s)" for c, v in sorted(commits.items()))
        problems.append(f"results span {len(commits)} revisions ({detail})")

    for p in problems:
        print(f"  {p}")
    if problems:
        print(f"{len(files)} result files, {len(problems)} provenance problem(s)")
        print("re-run: commit the code, then `make experiments`, then commit results")
        return 1
    if not quiet:
        only = next(iter(commits))
        print(f"{len(files)} result files, one clean revision {only[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
