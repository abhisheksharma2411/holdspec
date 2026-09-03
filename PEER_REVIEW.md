# Peer review — HoldSpec

Adversarial review run 2026-09-03. Claims checked against the result files.

**Recommendation: major revision.** The formal model and the differential
result are solid. The headline detection number is scoped in a way the paper
does not make clear, and the artifact has no provenance at all.

---

## Major

### 1. The 100% detection rate is measured inside the space that defines it

The paper reports that the generated suite detects **61 of 61** killable
mutants, against 56% for random and 69% for a hand-written suite.

"Killable" is established by exhaustive differential search **within the
model's bounds** (`e3_conformance.py`: `equivalent = diff is None`). The
generated suite is a BFS over that same bounded state space. So a mutant is
killable exactly when some sequence inside the bound distinguishes it, and the
suite enumerates sequences inside the bound.

This is not circular in the crude sense — killability is defined independently
of whether the suite happens to kill a mutant, and the random and hand-written
baselines are measured against the same definition, so the comparison is fair.
But 100% is close to structurally guaranteed, and the paper reads as though it
were an empirical ceiling.

**Fix:** state plainly that detection is complete *with respect to the model's
bounds*, that this is expected rather than surprising, and that the informative
numbers are the baselines' shortfalls under an identical budget. Consider
reporting detection against defects drawn from outside the bound.

### 2. No result file carries provenance

None of the seven result files contains a provenance block: no commit, no
version, no timestamp, no configuration hash. The companion papers at least
recorded a (broken) field. A reader cannot establish which code produced any
number here.

---

## Moderate

### 3. Percentages on 61 mutants, with no interval

56%, 69% and 67% are each one draw. The 2-point gap between the hand-written
suite (69%) and random at ten times the budget (67%) is well inside what 61
samples can resolve, and the paper should not lean on that ordering.

### 4. No provider was contacted

The paper states this clearly, in the abstract, which is the right place. Worth
keeping prominent under revision: every cross-provider divergence is derived
from documentation, so the strong claim that one adapter interface cannot sit
over both providers is a claim about the documents, not about the systems.

---

## Minor

- The abstract uses em-dash-joined clauses three times in its first two
  sentences. Flagged as an AI-style pattern in the companion review.
- `e5_equivalence` shows TLC and the Python model reaching identical state sets
  (131/131 on the default profile, 0 states unique to either). This is good
  cross-validation and deserves more than its current mention.
- Result files are bare lists in three cases, dicts in four. A uniform envelope
  with provenance would make the artifact easier to consume.

## What holds up

Macros are generated from the result files and every spot-checked value matches
(killable 61, model 100%, random 56%, hand-written 69%, random-10x 67%). The
equivalent-mutant treatment is genuine rather than a convenience. The budget
matching between the generated and random suites was corrected during
development and the corrected numbers are what is reported.
