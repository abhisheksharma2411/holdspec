"""Driving TLC over HoldSpec: config generation, invocation, output parsing."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

from .profiles import Profile

REPO = Path(__file__).resolve().parents[2]
SPEC_DIR = REPO / "spec"
TLA2TOOLS = REPO / "tools" / "tla2tools.jar"

INVARIANTS = [
    "TypeOK",
    "INV_CaptureWithinLimit",
    "INV_NoCaptureAfterClose",
    "INV_ReleaseAtMostOnce",
    "INV_NoReleaseBeforeClose",
    "INV_BoundedRelease",
    "INV_NoCaptureAfterExpiry",
    "INV_CaptureCountWithinProfile",
    "INV_HoldFullyReleased",
]

PROPERTIES = [
    "LIVE_EventualRelease",
    "LIVE_EventualClose",
    "LIVE_Termination",
]


def _tla_value(v) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    return str(v)


def write_config(
    profile: Profile,
    path: Path,
    invariants: Optional[List[str]] = None,
    properties: Optional[List[str]] = None,
) -> Path:
    """Emit a TLC .cfg for one profile."""
    invariants = INVARIANTS if invariants is None else invariants
    properties = PROPERTIES if properties is None else properties
    lines = [
        f"\\* Generated from holdspec.profiles: {profile.name} ({profile.provider}).",
        "\\* Do not edit by hand; run experiments/e1_model_check.py.",
        "SPECIFICATION Spec",
        "CONSTANTS",
    ]
    for k, v in profile.tla_constants().items():
        lines.append(f"    {k} = {_tla_value(v)}")
    for inv in invariants:
        lines.append(f"INVARIANT {inv}")
    for prop in properties:
        lines.append(f"PROPERTY {prop}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


@dataclass
class TLCResult:
    profile: str
    module: str
    config: str
    ok: bool
    states_generated: Optional[int]
    distinct_states: Optional[int]
    diameter: Optional[int]
    seconds: float
    violated: Optional[str]
    violation_kind: Optional[str]   # "invariant" | "property" | "deadlock" | "error"
    trace_length: Optional[int]
    stdout_tail: str

    def to_dict(self) -> dict:
        return asdict(self)


_RE_STATES = re.compile(
    r"(\d+) states generated(?:, (\d+) distinct states found)?"
)
_RE_DIAMETER = re.compile(r"depth of the complete state graph search is (\d+)")
_RE_INV = re.compile(r"Invariant (\w+) is violated")
_RE_PROP = re.compile(r"(?:Temporal properties were violated|property (\w+))")
_RE_ACTION_PROP = re.compile(r"Action property (\w+) is violated")
_RE_STATE_NUM = re.compile(r"^State (\d+):", re.M)


def run_tlc(
    module: str,
    config: Path,
    profile_name: str,
    workers: str = "auto",
    extra_args: Optional[List[str]] = None,
    timeout: int = 900,
) -> TLCResult:
    """Run TLC on `module` with `config` and parse the summary numbers."""
    if not TLA2TOOLS.exists():
        raise FileNotFoundError(
            f"{TLA2TOOLS} missing; run `make setup` to download tla2tools.jar"
        )
    java = shutil.which("java")
    if java is None:
        raise FileNotFoundError("java not found on PATH")

    cmd = [
        java,
        "-XX:+UseParallelGC",
        "-cp",
        str(TLA2TOOLS),
        "tlc2.TLC",
        "-config",
        str(config.resolve()),
        "-workers",
        workers,
        "-cleanup",
    ] + (extra_args or []) + [module]

    start = time.time()
    proc = subprocess.run(
        cmd, cwd=str(SPEC_DIR), capture_output=True, text=True, timeout=timeout
    )
    elapsed = time.time() - start
    out = proc.stdout + "\n" + proc.stderr

    states = distinct = diameter = None
    for m in _RE_STATES.finditer(out):
        states = int(m.group(1))
        if m.group(2):
            distinct = int(m.group(2))
    m = _RE_DIAMETER.search(out)
    if m:
        diameter = int(m.group(1))

    violated = kind = None
    m = _RE_INV.search(out)
    if m:
        violated, kind = m.group(1), "invariant"
    elif _RE_ACTION_PROP.search(out):
        violated = _RE_ACTION_PROP.search(out).group(1)
        kind = "property"
    elif "Temporal properties were violated" in out:
        # TLC names the property on the preceding line for PROPERTY checks.
        m2 = re.search(r"Error: Temporal properties were violated\.\s*\n\s*Error: The following behavior constitutes a counter-example", out)
        violated = _first_declared_property(config)
        kind = "property"
    elif "Deadlock reached" in out:
        violated, kind = "deadlock", "deadlock"

    trace_len = None
    nums = _RE_STATE_NUM.findall(out)
    if nums:
        trace_len = max(int(n) for n in nums)

    ok = proc.returncode == 0 and violated is None
    if not ok and violated is None:
        kind = "error"

    return TLCResult(
        profile=profile_name,
        module=module,
        config=str(config),
        ok=ok,
        states_generated=states,
        distinct_states=distinct,
        diameter=diameter,
        seconds=round(elapsed, 2),
        violated=violated,
        violation_kind=kind,
        trace_length=trace_len,
        stdout_tail=out[-4000:],
    )


def _first_declared_property(config: Path) -> Optional[str]:
    for line in config.read_text().splitlines():
        if line.startswith("PROPERTY"):
            return line.split(None, 1)[1].strip()
    return None


def save_results(results: List[TLCResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([r.to_dict() for r in results], indent=2) + "\n")
