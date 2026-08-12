# GA Readiness Status

**As of 2026-08-12.** This is a snapshot for whoever (human or AI coding agent) picks up
this repo next — read this before `specs/10-build-plan.md` if you're trying to figure
out what's actually done versus what the specs describe as intended. Specs describe the
target; this describes reality as of the date above. Update this file (don't just leave
it stale) as work continues.

## Two different completion numbers

**Code-complete against `specs/10-build-plan.md`: ~95%.** Phases 0–5 are fully built (see
git log — every phase has its own commits). Phase 6 (Hardening & GA gate) has 9 named
items; 6 are done, 1 is partial, 2 are untouched — see the breakdown below.

**Actual GA readiness: meaningfully lower, roughly 40–50%.** The gap between these two
numbers is the point of this document: almost everything still open is infrastructure
provisioning, external-party process, or real-world validation — not code. See §2 and §3.

## 1. Code gaps (buildable without new infrastructure, not yet done)

- **No OCR path.** `api/app/pipeline/detect.py` only handles born-digital PDFs
  (`ocr_confidence=None` always, by design — "Phase 1: born-digital only, no OCR path
  yet"). Scanned documents — common in government records — aren't processed at all.
- **No accuracy measurement exists.** `specs/05-redaction-pipeline.md`'s ~30-fixture
  golden suite and Phase 2's "nightly canary accuracy job" were never built
  (`tests/pipeline/golden/` is an empty scaffold). There's a live counter-example already
  failing: `api/tests/test_sample_document.py::test_sample_document_triggers_multiple_exemption_codes`
  fails because Presidio's SSN recognizer misses a detection in this environment.
- **A measured perf gap.** `api/app/services/review_service.py::bulk_update_candidates`
  has an N+1 `session.refresh()` loop; p95 latency measured ~650–700ms against
  `specs/01-product-spec.md` US-6's 300ms target (see `load-test/README.md`'s finding).
- **Two UI features flagged, never built:** a Cmd+K command palette, an Escalate button
  in the review workspace — both explicit spec gaps found during the accessibility pass.
- **Auth is dev-only.** Real Cognito signup returns `501 Not Implemented` until a user
  pool exists (`api/app/routers/auth.py`). WebAuthn/passkeys and SAML/OIDC SSO have zero
  implementation — not even unapplied Terraform, unlike everything in §2 below.

## 2. Infrastructure — written, never deployed

**Nothing in this repo has ever run `terraform apply` against a real AWS account.**
`infra/envs/` has only `dev/`. Everything below is code-complete (`terraform validate`
passes, matching `.github/workflows/ci.yml`'s terraform job exactly) but unproven against
reality:

- No staging or production environment exists.
- No S3 cross-region replication, despite `specs/08-security-compliance.md` committing
  to it (`infra/modules/storage` only configures versioning + per-org KMS today).
- Aurora's `backup_retention_days` defaults to 7, not the spec's 35-day production target
  (`infra/modules/aurora/variables.tf`).
- Aurora's log export to CloudWatch isn't enabled — needed for the RLS-violation and
  integrity-verifier-failure alarms (`infra/modules/alerting`) to receive any data once
  deployed; the app-side logging and the alarms themselves are both built and verified,
  just waiting on this.
- The alerting SNS topic has no subscriber — `pagerduty_integration_email` is empty
  because no paging vendor account exists yet.

## 3. Process/compliance — needs external parties, can't be done from a coding session

- A real third-party pentest (an internal security self-review exists — see git log for
  "Phase 6: security self-review" — but that's not a substitute).
- SOC 2 Type II evidence collection — needs a live production environment and an
  automation platform (Vanta/Drata) to collect evidence from.
- GovRAMP Security Snapshot submission — architecture is designed to cover the controls
  it checks; the submission itself hasn't happened.
- An on-call paging vendor account (PagerDuty or similar) — the SNS bridge to one is
  ready (`infra/modules/alerting`'s `pagerduty_integration_email` variable), nothing's
  subscribed.
- Load and restore drills at real scale — `load-test/hot-paths.js` and
  `api/scripts/dr_restore_drill.py` both prove the *mechanics* work (verified against a
  local Postgres and a local dev server), neither has run against real AWS or at
  anything close to 200 concurrent orgs.

## Confirmed next step

**Standing up real AWS infrastructure** (item 2 above) — chosen deliberately over the
code gaps or process items, because it unblocks the most other work: the real load test,
the real DR drill, alarms actually paging, and SOC 2/GovRAMP prep all wait on a real
environment existing at all.

Prerequisites before starting:
1. An AWS account with billing enabled.
2. A way to authenticate — an IAM user access key for the initial bootstrap, and/or a
   GitHub Actions OIDC role (`.github/workflows/ci.yml`'s terraform job is already
   written expecting this once it exists).
3. A region decision (code defaults to us-east-1/us-west-2 per the specs) and whether a
   real domain name is ready, or start on the default CloudFront hostname.

Rough planned sequence:
1. Bootstrap the Terraform state backend itself — an S3 bucket + DynamoDB lock table.
   `infra/envs/dev/backend.tf` is a partial `backend "s3" {}` block that needs
   `terraform init -backend-config=backend.hcl` (gitignored; see `backend.hcl.example`)
   pointing at these, and they must exist *before* `terraform init` can use them —
   Terraform can't create the place it stores its own state.
2. `terraform apply` the `dev` environment for the first time ever.
3. Verify against the real thing: the RLS test matrix against real Aurora, a real
   `api/scripts/dr_restore_drill.py` run against it, and `load-test/hot-paths.js` against
   a real deployed API instead of localhost.

## Related documents

- `docs/disaster-recovery-runbook.md` — restore procedure + drill; §9 has its own gaps list.
- `docs/on-call-runbook.md` — alarm response guidance; §5 has its own gaps list.
- `docs/ai-transparency/ai-transparency-one-pager.pdf` — AI governance transparency artifact.
- `load-test/README.md` — k6 load test usage and the latency finding above.
- `specs/10-build-plan.md` — the phased plan this status is measured against.
