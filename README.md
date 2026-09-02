# HoldSpec

A machine-checked model and conformance suite for the payment authorization
**hold** lifecycle: authorize, partial and multiple capture, void, expiry,
incremental authorization, and the release of held funds.

Every payment service provider implements these rules and none specifies them
formally. HoldSpec writes them down as a TLA+ state machine parameterized by a
provider capability profile, checks eight safety invariants and three liveness
properties over six profiles built from Stripe's and Adyen's published
documentation, and generates from the same machine a conformance suite that runs
black-box against a provider API.

```
make setup       # virtualenv + tla2tools.jar
make check       # model-check every provider profile
make test        # 39 unit and sanity tests
make experiments # E1-E6, writes results/
make figures     # regenerate figures from results/
make paper       # build paper/holdspec.pdf
make reproduce   # all of it, from a clean tree
```

## Headline results

| | |
| --- | --- |
| Profiles model-checked | 6, all 11 properties hold, 4,096 distinct states in 4.0 s |
| Specification mutations caught | 10 of 10, by the property each one targets |
| Seeded defects detected by the generated suite | 61 of 61 |
| ... by random testing at the same call budget | 34 of 61 |
| ... by random testing at ten times the budget | 41 of 61 |
| ... by a hand-written integration suite | 42 of 61 |
| Provider profile pairs that diverge | 15 of 15 |
| HTTP deployments conforming | 4 of 4, 12 of 12 injected defects found |

**No live provider was tested.** No sandbox credentials were available, so every
result concerns documented behavior. See [BLOCKERS.md](BLOCKERS.md).

## What is here

```
spec/HoldSpec.tla        the specification of record; profiles/ holds generated TLC configs
src/holdspec/
  profiles.py            provider capability vectors, each field quoted and cited
  model.py               executable mirror of the TLA+ module (E5 proves they agree)
  harness.py             the operations a black-box test may issue, and what must follow
  generator.py           suite construction and the two baselines
  runner.py              executing a suite against a system under test
  sut.py                 the reference PSP, written in the provider idiom
  mutants.py             twelve defects, one broken rule each
  differential.py        exhaustive product search: equivalent mutants, provider divergences
  http_sut.py            adapters for the Stripe-shaped and Adyen-shaped APIs
  live_sut.py            adapters for real sandboxes -- written, never run
  store.py               conformance run log and defect corpus
  tlc.py, dump.py        driving TLC and reading its state dump
docker/mock_psp/app.py   mock providers speaking each API shape over HTTP
experiments/             E1-E6 and run_all.py
paper/                   LaTeX, plus make_tables.py which generates every table
```

## Reading the artifact

Start with `spec/HoldSpec.tla`: eleven variables, eight actions, eleven
properties, and comments explaining why each guard is where it is. Then
`src/holdspec/profiles.py`, where every provider claim carries the URL and the
verbatim quotation it came from.

`EXPERIMENTS.md` is the honest log, including the three modelling errors the
HTTP run found and the two ways the cross-provider comparison first reported
nonsense. `REVIEW.md` maps each claim in the paper to the file that supports it.

## Running against a real sandbox

`src/holdspec/live_sut.py` has adapters for Stripe test mode and Adyen test
mode. They read `STRIPE_SECRET_KEY`, or `ADYEN_API_KEY` and
`ADYEN_MERCHANT_ACCOUNT`, and raise `LiveSandboxUnavailable` without them. They
have never been run. Two obstacles beyond credentials are documented in the
module: a real authorization cannot be fast-forwarded, so expiry tests either
wait days or are excluded, and Adyen reports modification outcomes by webhook
rather than in the response.

If you run them, the results would be worth more than anything in this
repository. Please open an issue.

## Optional services

```bash
docker compose up -d --wait
HOLDSPEC_DATABASE_URL=postgresql://holdspec:holdspec@localhost:55432/holdspec \
  make experiments
```

Brings up Postgres for the run log and one mock provider per API shape. Nothing
requires it: without Docker the mocks run as subprocesses and the log falls back
to SQLite.

## Artifact card

- **Inputs.** None. Provider profiles are version-controlled with a source URL
  and a quotation per field; all workloads are generated from the model at run
  time.
- **Outputs.** `results/*.json` (raw), `figures/*.pdf`, `paper/holdspec.pdf`,
  and a defect corpus of 235 violations each stored with a reproducing script.
- **Determinism.** TLC is exhaustive; model exploration is a deterministic
  breadth-first search; the one randomized component is seeded
  (`SEED = 20260901`). Re-running gives the same numbers.
- **Environment.** Python 3.12+, Java 17+ for TLC, a LaTeX distribution for the
  paper. Developed on Python 3.14.7, OpenJDK 25.0.2, TLC 2.19.
- **Runtime.** A few minutes for the full pipeline on a laptop.
- **License.** MIT.

## Citing

See `CITATION.cff`. The paper is `paper/holdspec.pdf`.

## Author

Abhishek Sharma, Senior Member, IEEE --- abhicse24@gmail.com ---
[github.com/abhisheksharma2411](https://github.com/abhisheksharma2411) ---
[abhisharma.co.in](https://abhisharma.co.in)
