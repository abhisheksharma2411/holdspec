"""Record which code produced which result file.

Each experiment here writes its own JSON in its own shape, and the readers in
``paper/make_tables.py`` depend on those shapes, so provenance is written
alongside rather than folded into them. ``results/PROVENANCE.json`` maps every
result file to a SHA-256 of its contents and to the commit, configuration and
interpreter that produced it, which is what makes a number in the paper
traceable to a revision.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def _git() -> dict[str, str]:
    info = {"commit": "uncommitted", "dirty": "unknown"}
    try:
        head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=5)
        if head.returncode == 0 and head.stdout.strip():
            info["commit"] = head.stdout.strip()
        status = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                                capture_output=True, text=True, timeout=5)
        if status.returncode == 0:
            info["dirty"] = "yes" if status.stdout.strip() else "no"
    except Exception:
        pass
    return info


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def write_provenance() -> Path:
    """Write ``results/PROVENANCE.json`` covering every result file present."""
    git = _git()
    files = {
        p.name: {"sha256_16": _digest(p), "bytes": p.stat().st_size}
        for p in sorted(RESULTS.glob("*.json"))
        if p.name != "PROVENANCE.json"
    }
    payload = {
        "git_commit": git["commit"],
        "git_dirty": git["dirty"],
        "python": platform.python_version(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": files,
    }
    out = RESULTS / "PROVENANCE.json"
    out.write_text(json.dumps(payload, indent=1) + "\n")
    return out


if __name__ == "__main__":
    path = write_provenance()
    data = json.loads(path.read_text())
    print(f"  wrote {path.name}: commit {data['git_commit'][:12]} "
          f"dirty={data['git_dirty']} over {len(data['files'])} result files")
