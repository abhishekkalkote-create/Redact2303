# RedactProof — Build Guide for Codex

RedactProof is a multi-tenant SaaS for AI-assisted, human-verified document redaction, sold to government agencies (FOIA/public-records teams) and regulated organizations.

**Core promise:** Upload records → AI proposes redactions with statutory exemption citations → humans review and edit → export permanently redacted files (with or without visible reasons) plus a court-ready exemption log — all inside a hard-isolated tenant with a complete audit trail.

## Spec files (read in this order when starting a phase)

| File | Contents |
|---|---|
| `specs/00-overview.md` | Vision, differentiators, competitive positioning, success metrics |
| `specs/01-product-spec.md` | Personas, user stories, workflows, functional requirements |
| `specs/02-architecture.md` | System architecture, tech stack, ADRs, AWS mapping |
| `specs/03-data-model.md` | Entities, PostgreSQL schema, RLS policies, state machines |
| `specs/04-api-spec.md` | REST API surface, auth, error model, conventions |
| `specs/05-redaction-pipeline.md` | Processing engine: OCR, detection passes, merge, verification |
| `specs/06-exemption-taxonomy.md` | Exemption codes, rule engine, rule packs, manual-to-rule extraction |
| `specs/07-ui-spec.md` | Screen-by-screen UI spec, review workspace, design standards |
| `specs/08-security-compliance.md` | Tenant isolation, encryption, audit, CJIS/SOC 2/GovRAMP alignment |
| `specs/09-admin-billing.md` | Usage metering, plans, invoicing, org admin, platform admin |
| `specs/10-build-plan.md` | Phased build plan with acceptance criteria per phase |

## Non-negotiable invariants (enforce in every PR)

1. **Tenant isolation is absolute.** Every table row, S3 key, queue message, cache key, and log line carries `org_id`. Postgres RLS is ON for all tenant tables. No query without tenant context. No cross-tenant data sharing, ever.
2. **Human in the loop.** No document can reach `exported` state without at least one human `review_completed` action. AI output is always a *suggestion* (`candidate`), never a final redaction.
3. **Redaction is destructive.** Exports burn redactions into the file (content removed, not overlaid), scrub metadata, and pass the integrity verifier (Section 7 of `specs/05-redaction-pipeline.md`) before being stored.
4. **Everything is audited.** Every state change writes an immutable `audit_events` row (append-only, hash-chained). No UPDATE/DELETE on audit tables.
5. **Every redaction has a reason.** A redaction cannot be approved without an exemption code (or org-defined reason code). Free-text justification optional but encouraged.
6. **No customer content in logs, traces, prompts stored at rest, or model training.** LLM calls go through the provider abstraction layer with zero-retention config.
7. **Usage is metered.** Every processed page emits a `usage_records` row at processing time. Billing derives from usage records only.

## Tech stack (see ADRs in `specs/02-architecture.md`)

- **Frontend:** Next.js 15 (App Router, TypeScript), Tailwind CSS, shadcn/ui, PDF.js for the review viewer, TanStack Query.
- **API:** Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, Pydantic v2.
- **Workers:** Python on SQS + ECS Fargate; PyMuPDF (fitz) + pikepdf for PDF work; Textract (scans) with Tesseract fallback; Microsoft Presidio + custom regex for deterministic detection; Amazon Bedrock (Codex) for contextual detection behind `app/llm/provider.py` abstraction.
- **Data:** Aurora PostgreSQL 16 (RLS), S3 (per-tenant prefix, per-tenant KMS key), Redis (ElastiCache) for queues state/rate limits only — no document content.
- **Auth:** Amazon Cognito (OIDC) + org-level SAML/OIDC SSO (Enterprise plan); FIDO2/WebAuthn MFA support.
- **Infra:** Terraform, AWS commercial (us-east-1/us-west-2) with GovCloud-portable choices only; CloudFront + WAF; GitHub Actions CI/CD.
- **Billing:** Stripe (metered subscriptions + invoicing) behind `app/billing/provider.py` abstraction (agencies often pay by PO/ACH — support Stripe Invoicing with net-30 terms, not just cards).

## Repository layout (monorepo)

```
/web           Next.js app
/api           FastAPI service (routers, services, models, auth, billing)
/workers       Processing pipeline (intake, ocr, detect, merge, export, verify)
/shared        OpenAPI-generated TS client, shared JSON schemas (manifest, rules)
/infra         Terraform
/specs         This spec package
/tests         API integration tests, pipeline golden-file tests, RLS tests
```

## Engineering conventions

- OpenAPI schema is the contract; generate the TS client from it (`/shared`). Never hand-write API types in the frontend.
- Async everything in the pipeline; API responses > 500 ms of work become jobs with SSE progress.
- Migrations: Alembic, one migration per PR, reversible.
- Tests required per phase: RLS isolation tests (attempt cross-tenant access must fail), pipeline golden-file tests (known input → expected manifest), export integrity tests (extract text over redacted boxes must return nothing).
- Feature flags per org (`org_settings.features`) for pilot gating.
- All timestamps UTC, `timestamptz`. IDs are ULIDs (`org_01H...`, `doc_01H...` prefixed).

## Build order

Follow `specs/10-build-plan.md` phases 0–6 strictly. Do not start a later phase until the prior phase's acceptance criteria pass. Phase 1 delivers the vertical slice: upload → detect → review → export → audit, single org.
