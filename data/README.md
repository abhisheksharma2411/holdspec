# There is no dataset

This artifact does not ship data, and the empty directory is deliberate rather
than an oversight.

Two things a dataset would normally hold live elsewhere:

**Provider behavior** is in `../src/holdspec/profiles.py`, as six capability
vectors. Every field carries the URL it was read from and a verbatim quotation,
so each one can be re-checked against the provider's documentation. Keeping them
as code rather than as a data file is what lets the same values parameterize the
TLA+ constants, the Python model, the reference implementation and the adapters
without a second copy drifting from the first.

**Test workloads** are generated at run time from the model, by
`../src/holdspec/generator.py`. A stored corpus of test sequences would be a
snapshot of what the generator produces, and would go stale the moment the
specification changed.

`make data` regenerates the TLC configuration files under `../spec/profiles/`
from `profiles.py`. That is the only generated input the pipeline needs.

What the runs *produce* is under `../results/`, including
`defect_corpus.json`: every conformance violation observed, stored with the
call sequence that reproduces it.
