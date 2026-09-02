# Review: claims against evidence

A pass over the paper asking, for each claim, what would have to be true for it
to be wrong, and whether anything in `results/` would have caught that.

## Claim-to-evidence matrix

| # | Claim in the paper | Evidence | Where | Verdict |
| --- | --- | --- | --- | --- |
| 1 | The lifecycle is modelled in TLA+ and eight safety invariants and three liveness properties hold for six provider profiles | TLC run per profile, exhaustive, all properties enabled | `results/e1_model_check.json`, Table II | Measured |
| 2 | Exhaustive checking is cheap enough to re-run on every change | 4,096 distinct states, 4.0 s total | `results/e1_model_check.json` | Measured |
| 3 | The checking is not vacuous | 10 targeted specification mutations, each caught by the property it targets with only that property enabled; 0 survive all properties | `results/e2_spec_mutation.json`, Table III | Measured |
| 4 | The Python model and the TLA+ module describe the same machine | Reachable state sets compared element by element via TLC `-dump`; identical for 6 of 6 | `results/e5_equivalence.json` | Measured |
| 5 | The generated suite detects every killable seeded defect | 61/61 across six profiles | `results/e3_conformance.json`, Table IV | Measured |
| 6 | It beats equal-budget random and a hand-written suite | 100% vs 56% vs 69%, matched API-call budgets within ~1% | `results/e3_conformance.json` | Measured |
| 7 | The gap is in sequence choice, not call volume | Random at 10x budget reaches 67%, still short of 100% | `results/e3_conformance.json` | Measured |
| 8 | Undetected mutants are undetectable, not missed | Exhaustive product search returns no distinguishing sequence within bounds; 11 of 72 pairs | `results/e3_conformance.json` (`equivalent_within_bounds`) | Measured, bounded |
| 9 | The suite runs black-box over HTTP against provider-shaped APIs | 4 deployments, 2 API shapes, all conform; 12/12 injected defects found | `results/e6_http_conformance.json`, Table V | Measured |
| 10 | Every profile pair diverges, up to 5 independent classes | 15 pairs compared exhaustively within bounds | `results/e4_cross_provider.json`, Fig. 3 | Measured, bounded |
| 11 | Stripe and Adyen differ on validity, over-capture, and how a remainder is released | Three pairs with shortest witnesses | `results/e4_cross_provider.json`, Table VI | Measured against documentation |
| 12 | Adyen has no final-capture flag, so one abstract operation is not expressible there | Provider documentation quoted in `profiles.py`; encoded as `supports_final_capture`; conformance failure that forced it is logged | `EXPERIMENTS.md` it. 7c | Measured against documentation |
| 13 | Neither the capture count nor the closure reason is a provider-neutral observable | Conformance failures in the HTTP run; Stripe documents `canceled` for both void and expiry | `EXPERIMENTS.md` it. 7a, 7b; `stripe2026hold` | Observed and documented |
| 14 | Violations are reproducible | 235 violations stored with the call sequence that produced each | `results/defect_corpus.json` | Measured |
| 15 | No live provider was tested | No credentials; adapters raise `LiveSandboxUnavailable` | `BLOCKERS.md` | Stated as a limitation |

Nothing in the paper is presented as measured that is not in this table.

## Claims deliberately not made

- Not "the first formal treatment of payments". Cryptographic payment protocols
  have been verified for decades (`NOVELTY.md`).
- Not "Stripe and Adyen behave as follows". Every provider statement is about
  documented behavior. The distinction is stated in the abstract, in
  \S\ref{sec:limitations}, and in `BLOCKERS.md`.
- Not "the suite finds all lifecycle defects". It finds all of *these twelve*,
  which cover each invariant and are drawn from defects seen in practice. A
  class nobody thought of is not in the denominator.
- Not "the model is complete". E2 shows each property has force, not that the
  set is exhaustive.
- No claim about acceptance anywhere.

## Where a reviewer should push

**"Your reference implementation and your oracle come from the same author's
reading of the same documents."** Correct, and it is why the reference is
written in the provider idiom rather than by calling the model, and why the
HTTP run exists. That run found three modelling errors that in-process testing
did not. It does not rule out a shared misreading of the documentation, and only
a live sandbox would.

**"A 100% detection rate suggests the defects were chosen to be findable."** The
mutants were fixed before the suite was tuned, and two of them -- the late
release and the missing release -- were *not* detected on the first run and
exposed an oracle bug (`EXPERIMENTS.md` it. 5). The rate reflects a suite that
covers the state space, not a curated defect list. The equivalent-mutant
analysis is the guard against the opposite error, counting undetectable defects
as misses.

**"The model is tiny."** Yes: 4 minor units, a handful of ticks, one hold. The
argument for sufficiency is in `ASSUMPTIONS.md` A1 -- no guard branches on
magnitude beyond a ceiling comparison. The argument does not extend to overflow
or to concurrency, and both are named as limitations.

**"The divergences are between your profiles, not between the providers."**
Fair. Each profile field carries the URL and the quotation it came from, so the
step from documentation to profile can be checked line by line. The step from
provider to documentation cannot be, here.

## Reproducibility check

`make reproduce` on a clean tree: creates the virtualenv, downloads
`tla2tools.jar`, regenerates the TLC configurations from `profiles.py`, runs 39
unit tests, runs E1 through E6, regenerates three figures, and builds the PDF.
Verified end to end on the machine described in `EXPERIMENTS.md`. Runtime is a
few minutes. Docker is optional; without it the mock providers run as
subprocesses and the run log falls back to SQLite.

Determinism: TLC is exhaustive, the model exploration is a deterministic BFS,
and the one randomized component is seeded (`SEED = 20260901`). Re-running gives
the same numbers.

No figure or table in the paper contains a hand-entered number.
`paper/make_tables.py` generates all six tables and the in-prose macros from the
JSON in `results/`; `figures/make_figures.py` generates all three figures from
the same files. The Zenodo DOI is the only externally supplied value, and it is
read from a file rather than typed into the LaTeX.

## Readiness

Ready to post as a preprint.

The work is complete against what it set out to do, with one exception that is
disclosed rather than hidden: it specifies and tests the lifecycle, and it does
not test a live provider. That gap is stated in the abstract, has its own
limitation paragraph, and is the stated next step. A reviewer who expects live
sandbox results will be disappointed, and will not be misled.

Before submission to a venue rather than a preprint server, the one thing worth
adding is a live sandbox run against at least one provider. It converts the
central question -- do providers do what they document -- from an open question
into a result, and every piece needed for it is already written.
