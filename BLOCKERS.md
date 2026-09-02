# Blockers

## B1 -- No PSP sandbox credentials (open)

**What is blocked.** The plan called for running the conformance suite against
at least one, preferably two, live PSP sandboxes (Stripe test mode, Adyen test
mode) and reporting the behavioral differences observed there.

**Why.** No `STRIPE_SECRET_KEY`, and no `ADYEN_API_KEY` / `ADYEN_MERCHANT_ACCOUNT`
in the environment, and no way to obtain them without a human creating accounts.

**Worked around, not skipped.** Three things were done instead, and the paper is
explicit about which is which.

1. Provider profiles were built from the providers' own published documentation,
   with the URL and the verbatim quote for every field recorded in
   `src/holdspec/profiles.py`. A reader can check each one.
2. The conformance suite runs black-box over HTTP against mock services that
   speak the providers' API shapes (`docker/mock_psp/app.py`), so the suite is
   demonstrably transport-independent rather than an in-process assertion.
3. Live sandbox adapters (`src/holdspec/live_sut.py`) are written against the
   published API references and ship unrun. They raise
   `LiveSandboxUnavailable` when credentials are absent.

**What a live run would add that this does not have.** Confirmation that the
providers behave as they document. Everything E4 reports is a divergence between
two *documented* lifecycles; whether each provider honors its own documentation
is exactly the question the suite exists to answer and the one still open.

**Two obstacles a live run will hit, beyond credentials.**

- *Expiry cannot be fast-forwarded.* A real authorization expires on the card
  network's clock, in days. Either a run waits, or the expiry-dependent tests are
  excluded; `SKIP_TIME_TESTS` marks the boundary.
- *Adyen answers asynchronously.* Capture and cancel outcomes arrive by webhook,
  not in the response, so a live Adyen run needs a notification endpoint. The
  adapter's `observe()` raises rather than pretending to poll.

## B2 -- Multiple partial captures is not self-service on Adyen (open)

Adyen's documentation states that the feature must be enabled by their support
team. Even with credentials, the `adyen_multiple_partial_captures` profile could
not be exercised on a fresh test account without that request being granted.

## B3 -- Overcapture and multicapture are priced features on Stripe (open)

Both are documented as available to accounts on interchange-plus pricing, with
others directed to contact support. A live check of the `stripe_overcapture` and
`stripe_multicapture` profiles depends on the account's plan, so a reader
reproducing the live run may find these profiles unavailable to them.

## Not blockers

- Zenodo and GitHub: no credentials were used, so the repository is committed
  and tagged locally with one-step instructions in `PUBLISH.md`.
- Docker: available and used for the optional Postgres run log, but not required.
  Experiments fall back to SQLite and subprocess-hosted mocks.
