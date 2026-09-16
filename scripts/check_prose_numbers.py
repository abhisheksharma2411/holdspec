"""Find numbers typed into the prose that no generated file supports.

These papers take their tables and their \\newcommand values from the results,
so a table cannot drift from the artifact. The prose can. A sentence saying
"the gate reaches 85.4 per cent" is a number a person typed, and re-running the
experiments does not update it -- it just makes the sentence wrong, quietly,
in the one part of the paper a reader actually reads.

This walks the prose, ignoring what is generated or unrelated, and reports
every remaining numeric literal together with whether the results support it. A
number the results do support is still worth flagging if it is typed rather
than substituted, because next time it may not be; the report separates the two
so the unsupported ones stand out.

Usage:  python scripts/check_prose_numbers.py [--all]
        --all also lists supported literals, which is the backlog rather than
        the alarm.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"
RESULTS = ROOT / "results"

#: Environments whose contents are not prose.
SKIP_ENVIRONMENTS = ("tabular", "verbatim", "lstlisting", "equation", "align",
                     "align*", "figure", "table", "table*", "figure*")

#: Things that look like numbers and are not claims.
IGNORE = re.compile(
    r"""
      \\cite\{[^}]*\}          # citations
    | \\ref\{[^}]*\}           # cross-references
    | \\label\{[^}]*\}
    | \\includegraphics(\[[^\]]*\])?\{[^}]*\}
    | \\input\{[^}]*\}
    | \\newcommand\{[^}]*\}(\{[^}]*\})?
    | \\begin\{thebibliography\}\{\d+\}   # the widest label, not a claim
    | ORCID:?\s*[\d-]+                    # the author's identifier
    | \d{4}-\d{4}-\d{4}-\d{4}             # any ORCID, however it is introduced
    | \\IEEEauthorblock[AN]\{
    | \\[a-zA-Z@]+             # every other control sequence, incl. macros
    | %.*$                     # comments
    | https?://\S+             # URLs
    | arXiv:\S+                # identifiers
    | 10\.\d{4,}/\S+           # DOIs
    """,
    re.VERBOSE | re.MULTILINE)

# 1{,}605 is one number: the braces are a LaTeX thin space. Matching
# without them splits it into 1 and 605 and reports the tail as unsupported,
# which is how this lint's first run produced three false alarms.
NUMBER = re.compile(
    r"(?<![\w.}])(\d{1,3}(?:(?:\{,\}|,|)\d{3})*(?:\.\d+)?)(?![\w{])")

#: Numbers that are never claims about results.
BORING = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
          "100", "1000", "2024", "2025", "2026", "2027"}


def prose(text: str) -> str:
    # The bibliography is dates and page numbers about other people's work.
    text = re.sub(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}",
                  " ", text, flags=re.DOTALL)
    for env in SKIP_ENVIRONMENTS:
        text = re.sub(rf"\\begin\{{{re.escape(env)}\}}.*?\\end\{{{re.escape(env)}\}}",
                      " ", text, flags=re.DOTALL)
    return IGNORE.sub(" ", text)


def supported() -> set[str]:
    """Every number the generated files and results contain, as strings."""
    out: set[str] = set()

    generated = (list(PAPER.glob("numbers.tex"))
                 + list((PAPER / "tables").glob("*.tex"))
                 + list(PAPER.glob("*_table.tex")))
    for gen in generated:
        for m in NUMBER.finditer(gen.read_text()):
            out.add(m.group(1).replace("{,}", "").replace(",", ""))

    def walk(node) -> None:
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)):
            out.add(str(node))
            out.add(f"{node:.1f}")
            out.add(f"{node:.2f}")
            if isinstance(node, float):
                for scale in (100, 1000):
                    out.add(f"{node * scale:.1f}")
                    out.add(f"{node * scale:.2f}")
                    out.add(str(round(node * scale)))
    for f in sorted(RESULTS.glob("*.json")):
        walk(json.loads(f.read_text()))
    return out


def allowed() -> dict[str, str]:
    """Design constants the prose states on purpose, with the reason.

    Not every number in a paper comes from a results file. A corpus parameter
    -- the retail amounts orders are drawn from, the tick length -- is a choice
    the paper has to state, and it lives in the code rather than in an output.
    Recording it here with its justification is better than widening the lint
    until it says nothing, and better than silence, because the next person to
    see the number can tell it was meant.
    """
    path = PAPER / "prose_numbers_allowed.json"
    return json.loads(path.read_text()) if path.exists() else {}


def main(argv: list[str]) -> int:
    show_all = "--all" in argv
    waived = allowed()
    texs = [p for p in PAPER.glob("*.tex")
            if p.name not in {"numbers.tex"} and "arxiv" not in p.name]
    if not texs:
        print("no paper/*.tex found")
        return 2

    known = supported()
    unsupported: list[tuple[str, int, str]] = []
    typed: list[tuple[str, int, str]] = []

    for tex in texs:
        # Stripped whole-file first, because thebibliography and the display
        # environments span lines and a per-line pass cannot see their extent.
        body = prose(tex.read_text())
        for lineno, line in enumerate(body.splitlines(), 1):
            for m in NUMBER.finditer(line):
                raw = m.group(1)
                plain = raw.replace("{,}", "").replace(",", "")
                if plain in BORING:
                    continue
                if plain in waived:
                    continue
                (typed if plain in known else unsupported).append(
                    (tex.name, lineno, raw))

    for name, lineno, raw in unsupported:
        print(f"  UNSUPPORTED  {name}:{lineno}  {raw}")
    if show_all:
        for name, lineno, raw in typed:
            print(f"  typed        {name}:{lineno}  {raw}")

    print(f"{len(typed) + len(unsupported)} numeric literals in prose: "
          f"{len(typed)} supported by the results, {len(unsupported)} not"
          + (f", {len(waived)} waived as design constants" if waived else ""))
    return 1 if unsupported else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
