# 02 — Architecture & Tech Stack

## System diagram

```
Browser (Next.js 15, TS)
   │ HTTPS (CloudFront + WAF)
   ▼
FastAPI service (ECS Fargate, autoscaled)          Aurora PostgreSQL 16
   ├── REST API (OpenAPI contract) ◄──────────────► (RLS on all tenant tables)
   ├── SSE progress streams
   ├── enqueue jobs ──► SQS (per job type: intake, ocr, detect, export)
   │                        │
   │                        ▼
   │                  Worker fleet (ECS Fargate, Python)
   │                    ├─ intake: validate, malware scan, page split
   │                    ├─ extract: PyMuPDF text / Textract OCR
   │                    ├─ detect: Presidio+regex pass → Bedrock contextual pass → merge
   │                    ├─ export: burn-in (PyMuPDF), metadata scrub (pikepdf)
   │                    └─ verify: integrity checker
   │                        │
   ▼                        ▼
S3 (per-org prefix, per-org KMS key): uploads / page-previews / manifests / exports
Redis (ElastiCache): rate limits, SSE fanout, job progress cache (no document content)
Stripe: metered billing, invoicing        Cognito: authn (OIDC), org SSO (SAML) later
CloudWatch + OpenTelemetry: metrics/traces (content-free)
```

## Architecture Decision Records

**ADR-1: TypeScript frontend + Python backend/workers.**
Python owns the only ecosystem that matters for this product's core: PyMuPDF/pikepdf (true destructive PDF redaction), Presidio (PII detection), OCR tooling, Bedrock SDK maturity. One backend language for API + workers keeps models/schemas shared. Next.js gives the best review-workspace UX and hiring pool. Rejected: full-TS (would force reimplementing PDF burn-in — the highest-risk component — on weaker libraries); rejected: Python-only with server templates (review workspace demands a rich SPA).

**ADR-2: Pooled multi-tenancy with Postgres RLS + per-tenant KMS keys, not DB-per-tenant.**
Pooled Aurora with RLS enforced via `SET LOCAL app.org_id` per request/job gives strong isolation, simple ops, and cheap tenants — with per-org S3 prefixes and per-org KMS keys providing cryptographic separation of content. DB-per-tenant deferred to an Enterprise "dedicated" tier if a large agency demands it; schema kept portable for that. RLS tests in CI are mandatory.

**ADR-3: AWS commercial first, GovCloud-portable always.**
Launch us-east-1/us-west-2 (US-only data residency contractually). Every service chosen must exist in GovCloud (Aurora, S3, SQS, ECS, KMS, Textract, Bedrock, Cognito ✔). No Vercel for production frontend (host web on ECS/CloudFront) to keep the boundary single-cloud for future GovRAMP/FedRAMP scoping.

**ADR-4: Async pipeline via SQS + Fargate workers, no Lambda for core processing.**
Redaction jobs are long (OCR minutes), memory-heavy, and need predictable scaling; Fargate workers with SQS visibility-timeout retry semantics beat Lambda's 15-min ceiling and cold-start variance. Page-level parallelism: extract/detect fan out per page batch (10 pages/task), merge joins results.

**ADR-5: Two-pass hybrid detection, LLM behind an abstraction.**
Deterministic pass (Presidio + org regex/dictionary rules) is fast/cheap/explainable; contextual LLM pass (Bedrock Claude) runs only on pages/chunks needing judgment. All LLM calls via `app/llm/provider.py` (model id, prompt version, zero-retention config, token accounting per org). Model + prompt version stamped on every candidate for auditability. Rejected: LLM-everything (cost, latency, explainability) and regex-only (can't do context — the differentiator).

**ADR-6: Manifest as the single source of truth for review state.**
A versioned JSON manifest per document (schema in `/shared/schemas/manifest.json`, persisted in Postgres + S3 snapshot on export) drives the review UI and the export engine. Exports render exclusively from the manifest — never from UI state.

**ADR-7: Cognito for authn; app-level RBAC in Postgres.**
Cognito is FedRAMP-authorized, cheap, supports OIDC/SAML federation per org (Enterprise SSO) and WebAuthn. Roles/memberships live in our DB (Cognito only authenticates). Rejected: Auth0/WorkOS (boundary and cost concerns for gov path); rejected: DIY auth (unjustifiable risk).

**ADR-8: Stripe behind a billing abstraction.**
Stripe metered subscriptions + Stripe Invoicing (net-30, ACH/PO-friendly) cover self-serve and agency payment reality. Usage truth lives in our `usage_records`; Stripe receives daily aggregated meter events. Abstraction layer so a gov-focused biller could replace Stripe without touching product code.

## Request lifecycle (tenant safety)

1. Every API request: authenticate (Cognito JWT) → load membership → `SET LOCAL app.org_id = :org` in the transaction → RLS enforces scoping.
2. Every SQS message body includes `org_id` + `actor_id`; workers set the same GUC before any query and construct S3 keys as `s3://{bucket}/{org_id}/...` only from the message, never from payload-derived paths.
3. Signed URLs: 5-minute expiry, single-object, generated server-side after an RLS-scoped ownership check.

## Environments & CI/CD

- `dev` (ephemeral preview per PR: web only, shared dev backend), `staging` (full stack, synthetic data only), `prod`.
- GitHub Actions: lint (ruff, eslint), typecheck (mypy, tsc), unit + RLS + golden-file pipeline tests, Terraform plan; deploy on tag. No real customer documents outside prod, ever.
- Secrets: AWS Secrets Manager; no secrets in env files or CI logs.

## Observability

- Content-free structured logs (org_id, doc_id, job ids, timings — never text spans or filenames beyond hashed form in shared infra logs).
- Metrics: queue depth, per-stage latency (p50/p95 against SLOs in 00-overview), OCR confidence distribution, LLM token spend per org, detection precision/recall on canary set (nightly).
- Alarms: SLO breach, DLQ non-empty, RLS policy violation attempts (log + page on-call), integrity-verifier failure (blocks export, pages on-call).

## Scaling posture

Stateless API + workers autoscale on queue depth/CPU. Aurora read replicas for dashboards/audit search. Page-preview rendering cached in S3. Target: 200 concurrent orgs, 50K pages/day on baseline infra; 10x by scaling workers only.
