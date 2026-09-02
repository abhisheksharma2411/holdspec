# Novelty and prior art

Prior-art search run 2026-09-01. Every work named below was checked against its
own record (arXiv abstract page, ACM DL entry, or the vendor's documentation),
not against a secondary summary.

## The claim

HoldSpec contributes a machine-checked state machine for the payment
authorization *hold* lifecycle -- authorize, partial and multiple capture, void,
expiry, incremental authorization, and the release of held funds -- parameterized
by a provider capability profile, together with a conformance suite generated
from that state machine and executable black-box against a provider API.

Stated precisely, so that it can be falsified:

1. A formal model of the auth-capture business-logic lifecycle, with eight safety
   invariants and three liveness properties, model-checked exhaustively for six
   provider profiles.
2. A conformance suite derived from that model rather than written by hand, whose
   detection power is measured against seeded defects and compared with two
   baselines under the same oracle and the same API-call budget.
3. A differential procedure that finds, exhaustively within the model's bounds,
   every behavioral divergence between two provider profiles, each with an
   executable witness sequence.

## What we do not claim

- Not the first formal work on payments. Cryptographic payment protocols have
  been verified for decades; the lifecycle *above* the protocol is what is new
  here.
- Not a verified implementation. The reference PSP is a model-conformant
  implementation used to measure the suite, not a production gateway.
- No results from a live PSP sandbox. No credentials were available (BLOCKERS.md).
  The live adapters exist and are documented as untested.
- Nothing about exactly-once delivery or idempotency. That is the companion
  work's subject; the scope table below draws the line.

## Closest prior work, and why this is not it

**The EMV Standard: Break, Fix, Verify.** Basin, Sasse and Toro-Pozo, IEEE S&P
2021 (arXiv:2006.08249). A symbolic Tamarin model of the EMV protocol that found
two attacks on contactless transactions. The object of study is the
card-terminal cryptographic protocol -- authentication, transaction
authorization at the point of sale -- not what a merchant may afterwards do to
the resulting authorization. EMV says nothing about partial capture, void after
capture, or the release of a hold.

**Towards a Formal Verification of the Lightning Network with TLA+.** Grundmann
and Hartenstein, 2023 (arXiv:2307.02342). The nearest methodological analogue:
TLA+ plus a refinement chain to keep a payment protocol's state space tractable.
Different domain -- payment channels on Bitcoin -- and different question. We
borrow the method, including the practice of reporting state counts and search
depth rather than asserting that a model was checked.

**Smart Casual Verification of the Confidential Consortium Framework.** Howard,
Kuppe, Ashton, Chamayou and Crooks, NSDI 2025 (arXiv:2406.17455). Binds a TLA+
specification to a C++ implementation with trace validation in CI, and found six
bugs. This is the closest work on the *relationship* between a spec and an
implementation, and it is what E5 and E6 are modeled on. It validates traces of a
system whose source is available; our system under test is a third-party API
whose internals cannot be traced, so the binding has to be black-box conformance
rather than trace refinement.

**Differential Regression Testing for REST APIs.** Godefroid, Lehmann and
Polishchuk, ISSTA 2020. Differential testing of REST API versions to find
breaking changes, driven by the API's specification. The technique is close
kin. The differences: the comparison there is between versions of one service
and is driven by a syntactic interface description, while here it is between two
providers of the same business capability and is driven by a semantic state
machine, so a divergence comes back as a lifecycle rule rather than a schema
change.

**Provider documentation.** Stripe and Adyen each document their own lifecycle
carefully. Neither publishes a machine-checkable model, and neither documents
the other, which is exactly the gap E4 fills: the divergences it reports are
consequences of the two documentation sets that neither set states.

## Scope against the idempotency companion (T8)

The two are disjoint, and the boundary is the object each one is about.

| Question | T8 (payment idempotency) | HoldSpec |
| --- | --- | --- |
| Object | one operation, retried | one authorization, over its life |
| Failure guarded against | a duplicate external effect | money held or taken wrongly |
| Central identity | the operation key | the hold |
| Typical rule | a retry with the same key must not charge twice | captures must not exceed what was authorized |
| Time | retry windows, key lifetime | authorization validity, release deadline |
| Actions modelled | submit, retry, reconcile | authorize, capture, void, expire, release |

An implementation can be perfectly idempotent and still capture after a void; it
can be correct about holds and still double-charge on a retry. Neither result
implies the other.

## Prior-art queries run

- formal verification payment authorization capture void expiry lifecycle TLA+
- conformance testing payment service provider API state machine model-based testing
- arXiv formal model auth capture payment gateway lifecycle model checking invariants
- differential testing payment APIs cross-provider behavioral differences
- payment idempotency formal contract conformance suite

Nothing surfaced that models the auth-capture lifecycle itself. Adjacent 2026
work on agentic-payment protocols (x402 security analysis, arXiv:2605.30998; AP2
runtime verification, arXiv:2602.06345) studies protocol-level invariants for
agent-initiated payments, a different layer.
