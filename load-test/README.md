# Load test

Phase 6 build-plan item: "load test to SLOs (k6: 200 concurrent orgs simulated)."

## What it does

`hot-paths.js` simulates concurrent orgs, each running its own full first-session
lifecycle against the API's hottest path: dev-login → create org → process the free
sample document → approve every candidate (closing any remaining occurrences via
search-and-redact, same as a real reviewer would) → complete review → export. Every
iteration mints a fresh org, so N VUs really is N concurrent orgs, not N requests against
one shared tenant.

## Running it

```bash
# API must be running with ENV=local (dev auth enabled) — this never touches real Cognito.
cd api && source .venv/bin/activate && uvicorn app.main:app

# Local smoke run (small, fast — proves the script works):
BASE_URL=http://localhost:8000 TARGET_VUS=5 k6 run load-test/hot-paths.js

# The "real" Phase 6 run (against a real deployed environment):
BASE_URL=https://staging.example.com TARGET_VUS=200 RAMP_DURATION=2m HOLD_DURATION=5m \
  k6 run load-test/hot-paths.js
```

## What this proves and what it doesn't

The sample document is a single synthetic page, not the golden-fixture 20-page/500-page/
100-page documents `specs/00-overview.md`'s Performance SLOs table benchmarks against —
so the upload/review/export timings here are a proxy at a much smaller scale, not a
literal test of those page-count-scaled targets. Those need the real fixtures and a real
deployed environment (staging or production), neither of which exists in this sandbox —
running `TARGET_VUS=200` here would load-test my own laptop's Postgres, not anything
meaningful about production capacity.

What **is** a direct, size-independent check: `specs/01-product-spec.md` US-6's own
target, "p95 action latency < 300ms" for candidate approve/reject actions. That threshold
is real and literal (`review_action_ms` in the script), not scaled down for this
environment.

## A finding from actually running this

Running the smoke test locally, `review_action_ms` p95 lands around 650–700ms — missing
the 300ms target by more than 2x, consistently, even at TARGET_VUS=3. `checks_succeeded`
is 100% (no errors, just slow) so this isn't a correctness bug. A likely contributor,
found by reading `app/services/review_service.py::bulk_update_candidates` while
investigating: it does `await session.refresh(c)` in a loop, once per approved candidate
— an N+1 round-trip pattern (one extra sequential SELECT per candidate, purely to pick up
DB-side defaults like `updated_at`). This is plausible but not confirmed as *the* cause on
this hardware (a shared local Postgres on a laptop, not provisioned Aurora, is itself a
confound) — flagged here as a concrete lead for whoever picks up the next latency pass,
not fixed as part of building this load-test script.

## Prerequisites

- `k6` (`brew install k6`).
- The API running locally or against a real environment, with dev auth enabled
  (`ENV=local`, or another env with `dev_auth_enabled=true` — never real Cognito).
