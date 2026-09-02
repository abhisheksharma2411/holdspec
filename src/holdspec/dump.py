"""Parsing TLC's state dump, so the Python model can be compared against TLC."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Set

from .model import State
from .profiles import Profile
from .tlc import SPEC_DIR, TLA2TOOLS

_ASSIGN = re.compile(r"^/\\ (\w+) = (.+)$")

_FIELDS = {
    "state", "closedBy", "authAmt", "capturedTotal", "capturedAtClose",
    "captureCount", "lastCaptureAt", "released", "expiresAt", "releaseDue", "clock",
}


def _value(raw: str):
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return int(raw)


def parse_dump(path: Path) -> Set[State]:
    """Read a TLC `-dump` file into a set of States.

    TLC lists each reachable state; duplicates in the file are collapsed here.
    """
    states: Set[State] = set()
    current: dict = {}
    for line in path.read_text().splitlines():
        line = line.rstrip()
        if line.startswith("State ") and line.endswith(":"):
            if current:
                states.add(State(**current))
            current = {}
            continue
        m = _ASSIGN.match(line)
        if m:
            name, raw = m.group(1), m.group(2)
            if name in _FIELDS:
                current[name] = _value(raw)
    if current:
        states.add(State(**current))
    return states


def tlc_state_set(profile: Profile, config: Path, out_dir: Path) -> Set[State]:
    """Run TLC with -dump for `profile` and return the reachable state set."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"{profile.name}_states"
    java = shutil.which("java")
    if java is None:
        raise FileNotFoundError("java not found on PATH")
    cmd = [
        java, "-cp", str(TLA2TOOLS), "tlc2.TLC",
        "-config", str(config.resolve()),
        "-workers", "1",
        "-cleanup",
        "-dump", str(stem),
        "HoldSpec",
    ]
    proc = subprocess.run(cmd, cwd=str(SPEC_DIR), capture_output=True, text=True, timeout=1800)
    dump = Path(str(stem) + ".dump")
    if not dump.exists():  # pragma: no cover - only on a TLC failure
        raise RuntimeError(
            f"TLC produced no dump for {profile.name}:\n{proc.stdout[-2000:]}"
        )
    return parse_dump(dump)
