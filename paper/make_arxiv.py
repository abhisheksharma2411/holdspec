"""Build a self-contained arXiv submission from the repository layout.

The repository keeps figures in ../figures/ and tables in tables/, which is the
right layout for a repository and the wrong one for arXiv: a submission may not
reference anything above its own root, and the build runs with whatever files
are in the tarball and nothing else. This flattens the tree, rewrites the paths,
and carries the .bbl because arXiv does not run BibTeX.

The output is verified by compiling it in a scratch directory containing only
the submission files, which is the closest local approximation of what arXiv
does.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

PAPER = Path(__file__).resolve().parent
REPO = PAPER.parent
OUT = PAPER / "arxiv"
TARBALL = PAPER / "holdspec-arxiv.tar.gz"

FIGURES = ["fig1_state_space.pdf", "fig2_detection.pdf", "fig3_divergence.pdf"]


def build() -> Path:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    tex = (PAPER / "holdspec.tex").read_text()
    # Figures move from ../figures/ into the submission root.
    tex = re.sub(r"\{\.\./figures/([^}]+)\}", r"{\1}", tex)
    # Tables move from tables/ into the submission root.
    tex = re.sub(r"\\input\{tables/([^}]+)\}", r"\\input{\1}", tex)
    (OUT / "holdspec.tex").write_text(tex)

    for name in FIGURES:
        shutil.copy2(REPO / "figures" / name, OUT / name)
    for table in (PAPER / "tables").glob("*.tex"):
        shutil.copy2(table, OUT / table.name)

    bbl = PAPER / "holdspec.bbl"
    if not bbl.exists():
        raise SystemExit("holdspec.bbl is missing; run `make paper` first")
    shutil.copy2(bbl, OUT / "holdspec.bbl")

    with tarfile.open(TARBALL, "w:gz") as tar:
        for f in sorted(OUT.iterdir()):
            tar.add(f, arcname=f.name)
    return TARBALL


def verify() -> bool:
    """Compile the submission alone, in a directory holding nothing else."""
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        with tarfile.open(TARBALL) as tar:
            tar.extractall(scratch)
        # arXiv runs latex/pdflatex, never bibtex; the .bbl has to carry it.
        for _ in range(3):
            proc = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "holdspec.tex"],
                cwd=scratch, capture_output=True, text=True,
            )
        pdf = scratch / "holdspec.pdf"
        if proc.returncode != 0 or not pdf.exists():
            print(proc.stdout[-3000:])
            return False
        log = (scratch / "holdspec.log").read_text()
        pages = re.search(r"Output written on holdspec\.pdf \((\d+) page", log)
        missing = [l for l in log.splitlines()
                   if "not found" in l.lower() or "Undefined control" in l]
        undefined = log.count("There were undefined references")
        print(f"  compiled standalone: {pages.group(1) if pages else '?'} pages")
        print(f"  missing files: {len(missing)}")
        print(f"  undefined references: {undefined}")
        for line in missing[:5]:
            print("   ", line.strip())
        return not missing and undefined == 0


def main() -> int:
    print("building arXiv submission")
    tarball = build()
    size = tarball.stat().st_size / 1024
    print(f"  {tarball.name} ({size:.0f} KB), {len(list(OUT.iterdir()))} files")
    print("verifying it compiles with nothing else present")
    ok = verify()
    print("  OK" if ok else "  FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
