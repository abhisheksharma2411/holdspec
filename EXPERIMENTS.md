# Experiment log

Every run, in order, with what it produced and what was changed because of it.
Seeds are fixed (`SEED = 20260901` in E3); TLC runs are exhaustive and
deterministic, so the numbers reproduce exactly. Raw output is under `results/`.

Machine: Apple Silicon, macOS 26.5, Python 3.14.7, OpenJDK 25.0.2,
TLC 2.19 (rev 5a47802), Docker 29.2.1 (optional).

---

## Iteration 1 -- the first specification did not hold

Ran TLC on `stripe_card_default` with all invariants. `INV_BoundedRelease`
failed after four steps: a hold closed, `releaseDue` was set, and `Tick` then
advanced the clock past it without anything obliging the release to happen.

The invariant was right and the specification was wrong. Time was unconstrained,
so the model permitted exactly what the invariant forbade.

**Change.** Adopted the upper-bound-timer treatment of real time: `Tick` is
disabled while a release is overdue. A missed deadline now shows up as a
timelock rather than as an invariant that cannot hold.

## Iteration 2 -- the release deadline could exceed the horizon

With time bounded, `TypeOK` failed: `Expire` could fire at the horizon and set
`releaseDue` to horizon + 2, outside its declared range.

Two options: widen the type, or make expiry urgent as well. Urgency is the more
faithful model -- an authorization does expire at its deadline, and it is the
*release* that is allowed to lag -- so `Tick` is now also disabled once a hold
has reached its expiry instant.

**Result.** All six profiles pass all eleven properties.

| Profile | States | Distinct | Depth | Time |
| --- | --- | --- | --- | --- |
| stripe_card_default | 182 | 131 | 9 | 0.6 s |
| stripe_multicapture | 1,032 | 642 | 11 | 0.7 s |
| stripe_overcapture | 215 | 155 | 9 | 0.6 s |
| adyen_card_default | 249 | 182 | 10 | 0.6 s |
| adyen_multiple_partial_captures | 1,067 | 738 | 12 | 0.7 s |
| incremental_auth | 3,509 | 2,248 | 11 | 0.8 s |

## Iteration 3 -- E5, do the two models agree?

The Python model reproduced TLC's distinct-state counts exactly on the first
run, which is suggestive and not sufficient: equal cardinality is not equal
membership. Compared the actual state sets through TLC's `-dump`. Identical for
all six profiles, and re-checked after every subsequent specification change.

## Iteration 4 -- E2, is the checking vacuous?

Ten targeted mutations of the specification. First run: all ten caught, but only
six by the property they targeted. TLC stops at the first property that fails,
and with everything enabled both ceiling mutations tripped `TypeOK` first while
two of the three fairness mutations tripped `EventualRelease`.

**Change.** Each mutation now runs twice, once with everything enabled and once
with only its own property. With correct attribution: 10 of 10 caught by the
property aimed at them, 0 surviving every property.

## Iteration 5 -- E3, first conformance run

Model-derived suite against 12 mutants on `stripe_card_default`: nine detected,
three missed -- `M02_capture_after_expiry`, `M07_no_release`,
`M08_late_release`.

Diagnosis separated two causes.

`M07` and `M08` were an oracle bug. `ReleaseHold` set `releaseDue` back to a
sentinel, so after a release the model could no longer say the release had been
due -- and a provider that released late became indistinguishable from one that
released on time.

**Change.** `ReleaseHold` leaves `releaseDue` in place, in both the TLA+ module
and the Python model. Both mutants are now detected. State counts rose (131 to
131 here, 1,161 to 1,568 on the largest profile at the time) and E5 was re-run.

`M02` was not a bug. It is masked by the auto-expiry on tick, so no call
sequence can reveal it.

## Iteration 6 -- classifying equivalent mutants

Rather than assume which undetected mutants were undetectable, added an
exhaustive breadth-first search over the product of mutant and reference under
identical call sequences. It returns the shortest distinguishing sequence, or
nothing if none exists within the profile's bounds.

`M02_capture_after_expiry` and `M09_void_after_partial` on single-capture
profiles: equivalent. `M01_capture_after_close`: distinguished in three calls,
`authorize(4) ; void() ; void()`.

Equivalent mutants are excluded from detection rates. Across six profiles, 11 of
72 mutant--profile pairs are equivalent and 61 are killable.

## Iteration 7 -- E6, over HTTP, and three real modelling errors

Ran the identical suite against mock services speaking Stripe's and Adyen's
request shapes. Three of four deployments conformed; the Adyen
multiple-partial-captures deployment failed. Each failure was a defect in the
model, not in the adapter.

**7a. The capture count is not provider-neutral.** 176 failures, first at
`capture(1, final=True)`: the model expected one capture, the adapter had made
two, because closing a hold on Adyen is a capture followed by a cancel. Removed
the capture count from the observable surface; detection stayed at 61/61.

**7b. The closure reason is not observable at all.** 100 failures, first at
`capture(1, final=False) ; void()`, where the model called the closure a void
and the service called it a capture. Checking showed neither provider reports a
closure reason synchronously -- a Stripe PaymentIntent that was voided and one
that expired uncaptured both read `canceled`. Removed; detection stayed at
61/61.

**7c. Adyen has no final-capture flag.** 30 failures, first at a third capture
after two non-final ones. Adyen's API cannot say "this capture is the last one",
so a merchant closes a hold either by capturing the whole authorized amount or
by cancelling the remainder.

**Change.** Added `SupportsFinalCapture` to the profile, the TLA+ specification,
the Python model, the reference implementation and both adapters. A capture that
consumes the entire authorized amount closes the hold on any profile; a capture
that leaves a remainder closes it only where the flag exists. Re-ran E1 and E5.

**Result.** All four deployments conform; all 12 injected defects detected
through the network interface.

## Iteration 8 -- E4, and two ways to report nonsense

First run of the cross-provider comparison on Stripe-default versus
Adyen-default returned 18 divergent sequences.

**8a. Horizon artifacts.** Each profile's clock bound is derived from its own
validity window, so the shorter-horizon side stopped advancing first and the
saturation was reported as a behavioral difference. Three of the four apparent
divergence classes were this. Fixed by giving both sides the larger horizon;
the pair then had exactly one difference.

**8b. Over-counting.** Grouping on the exact observation split one disagreement
into eight, since the captured amount carried along the way differed. Grouping
on which attributes disagree, and separately on the call kind rather than its
amount, collapsed the Stripe/Adyen multicapture pair from ten classes to four
real ones. The amounts are kept alongside each class, because for a bound like
over-capture the amount at which behavior changes is the finding.

## Iteration 9 -- E3, the random baseline had 20x the budget

The random arm was budgeted by sequence length while the model suite's cost was
counted including refusal checks, so random was making about twenty times as
many calls -- 42,147 against 2,089 on the smallest profile. The generated suite
still won, but the comparison as described was not the comparison being run.

**Change.** The random suite now accounts for refusal checks as it builds, so
budgets match within about 1%. Added a second arm at ten times the budget to
separate choosing the wrong calls from not making enough of them.

**Result.** Model 100% (61/61), random at matched budget 56% (34/61), random at
ten times budget 67% (41/61), hand-written 69% (42/61).

---

## Final numbers

| Experiment | Result |
| --- | --- |
| E1 model checking | 6 profiles, 11 properties each, all hold; 4,096 distinct states; 4.0 s |
| E2 spec mutation | 10 mutations, 10 caught by the property they target, 0 survivors |
| E3 conformance | 61 killable defects: model 100%, random 56%, random x10 67%, hand-written 69% |
| E4 cross-provider | 15 pairs, all diverge, up to 5 independent classes |
| E5 model equivalence | 6 of 6 profiles, state sets identical |
| E6 HTTP | 4 of 4 deployments conform, 12 of 12 injected defects detected |
| Defect corpus | 235 violations recorded with a reproducing script |

## Things that did not work, kept here so they are not retried

- Leaving the clock unconstrained and expressing timing purely as invariants.
  It makes the specification permit what the invariant forbids (iteration 1).
- Comparing two providers without equalizing the clock bound (iteration 8a).
- Grading providers on a capture count or a closure reason (iterations 7a, 7b).
  Both feel like natural observables and neither is one.
