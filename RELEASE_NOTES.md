# HoldSpec 1.0.0

First release: the artifact accompanying *HoldSpec: A Machine-Checked Model and
Conformance Suite for the Payment Authorization Hold Lifecycle*.

## What it contains

- A TLA+ specification of the payment authorization hold lifecycle,
  parameterized by a provider capability profile, with eight safety invariants
  and three liveness properties.
- Six provider profiles built from Stripe's and Adyen's published documentation,
  each field carrying its source URL and a verbatim quotation.
- A conformance suite generated from the model, executable black-box over HTTP,
  with an oracle derived from the same model.
- Twelve seeded defects and an exhaustive procedure for deciding which of them
  any call sequence can detect.
- A differential procedure that enumerates behavioral divergences between two
  provider profiles, with a shortest witness for each.
- Mock providers speaking Stripe's and Adyen's request shapes, and unrun
  adapters for their real sandboxes.
- Six experiments that regenerate every number and figure in the paper.

## Results reproduced by `make reproduce`

All eleven properties hold for all six profiles (4,096 distinct states, 4.0 s).
Ten specification mutations, each caught by the property it targets. The
generated suite detects 61 of 61 killable seeded defects, against 34 for
equal-budget random testing, 41 for random testing at ten times the budget, and
42 for a hand-written suite. All fifteen profile pairs diverge. All four HTTP
deployments conform and all twelve injected defects are detected through the
network interface.

## Known limitation

No live provider sandbox was tested; no credentials were available. Every result
concerns documented behavior. The adapters that would test a live provider are
included and marked as never having been run. See `BLOCKERS.md`.

## License

MIT.
