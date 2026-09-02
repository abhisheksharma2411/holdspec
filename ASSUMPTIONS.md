# Assumptions and the decisions behind them

Choices that were not forced by the problem, with what each one costs.

## A1 -- Money and time are small integers in the model

The model uses an authorized amount of 4 minor units and a validity window of 3
or 4 ticks. Real amounts and real windows (7 to 30 days) appear only in the
profile's `documented_*` fields and in the paper's comparison tables.

*Why.* The properties at stake -- a capture ceiling, a capture after a deadline,
a release that happens once -- are about ordering and comparison, not about
magnitude. Nothing in the state machine branches on the size of a number beyond
the ceiling comparison, so the small model retains every behavior the large one
has.

*What it costs.* An implementation defect that only appears at a particular
magnitude, such as an integer overflow on a large capture or a currency with a
different minor-unit scale, is out of reach. The ordering between providers is
preserved under the rescaling (a longer documented window gets a larger tick
budget), so the divergences E4 reports survive, but their sizes in days do not
come from the model.

## A2 -- One authorization at a time

The model has a single hold. Concurrent authorizations on one card, and
concurrent requests against one authorization, are out of scope.

*Why.* The properties under study are per-hold. Adding concurrency multiplies
the state space without changing any of the eight invariants.

*What it costs.* A race between a capture and a void arriving together is not
modelled, and that is a real class of production defect. It needs the operation
identity that the idempotency companion supplies, so it belongs there.

## A3 -- Expiry is urgent; releasing the funds is not

Time cannot advance past the moment an authorization expires, so a hold closes
at its deadline. Releasing the held funds may lag, by up to the profile's
`max_release_delay`, and the clock is blocked once that release is overdue.

*Why.* This is the standard upper-bound-timer treatment of real time in TLA+: an
action with a deadline blocks the clock, so a missed deadline shows up as a
timelock rather than passing unnoticed. Modelling the two differently reflects
what the providers describe -- the authorization lapses on the network's
schedule, while the cardholder's available balance is restored with some lag.

*What it costs.* Providers that are slow to *notice* an expiry are not
distinguished from ones that are prompt. Because the release lag is a permitted
range rather than a value, the oracle accepts either behavior inside the window;
outside it, `INV_BoundedRelease` fires.

## A4 -- Three fields are not treated as observable

`released` is checked against a permitted set rather than an exact value (see
A3). The number of capture calls and the reason a hold closed are not observed
at all.

*Why.* Neither is provider-neutral. Releasing a remainder is a zero-amount
capture on Stripe and a cancel on Adyen, so a capture count means different
things on the two rails. And no provider reports a closure reason
synchronously: a Stripe PaymentIntent that was voided and one that expired
uncaptured both read `canceled`.

*What it costs.* An implementation that voids a hold when it should have let it
expire is not caught. Removing both fields cost nothing measurable -- the
detection rate stayed at 61/61 -- but that is evidence about these twelve
mutants, not a proof that no defect needs them. Reading the event stream would
restore the distinction, and is the obvious next step.

## A5 -- Profiles are documentation, not observation

Each profile field is what the provider publishes, quoted and cited in
`src/holdspec/profiles.py`. None was confirmed against a live API (BLOCKERS.md).

*What it costs.* Everything E4 reports is a divergence between two documented
lifecycles. If a provider's behavior differs from its documentation, this work
does not detect it -- it produces the suite that would.

## A6 -- The reference implementation is written in the provider idiom

The reference PSP keeps a status string, an authorized amount, a capturable
amount, and a received amount, and an adapter maps that back to the abstract
observation. It does not call the model.

*Why.* Grading an implementation against a model it is a copy of measures
nothing. The translation layer is where the suite's assumptions get tested, and
E6 found two real modelling errors there -- the missing final-capture
capability and the non-neutral observables of A4.

*What it costs.* The reference is still one author's reading of the
documentation. It is a control for measuring the suite, not evidence about any
provider.

## A7 -- Equivalent mutants are excluded from the detection rate

A mutant that no call sequence can distinguish from the reference is reported
separately rather than counted as a miss. Equivalence is established by
exhaustive product search within the profile's bounds, not assumed.

*Why.* Counting an undetectable defect as a suite failure understates every
suite equally but makes the numbers meaningless.

*What it costs.* "Equivalent" means equivalent within the model's bounds. A
mutant might be distinguishable at an amount or a horizon the search does not
reach.

## A8 -- The random baseline gets the model suite's API-call budget

The random suite is allowed exactly as many calls against the system under test
as the model-derived suite makes, and uses the same oracle.

*Why.* The comparison is about how call sequences are chosen. Giving the
baselines a weaker oracle would measure the oracle instead, and giving them
fewer calls would measure the budget.

*What it costs.* The handwritten baseline is not budget-matched -- it is eight
to ten short tests without exhaustive rejection checks, because that is what it
is meant to represent. Its call count is reported alongside its detection rate
so the two are not confused.

## A9 -- Pairs are compared on a shared clock bound

When two profiles are compared, both are given the larger of the two horizons.

*Why.* Without it the profile with the shorter horizon simply stops advancing
sooner, and the saturation is reported as a behavioral difference. This was not
a hypothetical: before the shared bound was introduced, the Stripe/Adyen
comparison reported four divergence classes, three of which were this artifact.
