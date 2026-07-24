# 10 — Phased Build Plan (for Claude Code)

Rules: complete phases in order; a phase is done only when all acceptance criteria (AC) pass as automated tests where testable; keep `main` deployable; every phase ends with updated seed data + demo script.

## Phase 0 — Foundation (repo, infra, auth skeleton)
Build: monorepo layout per CLAUDE.md; Terraform for VPC, Aurora, S3 (+KMS), SQS, ECS services, Cognito, CloudFront; FastAPI skeleton with health, OpenAPI, error model, request-context middleware (org GUC); Next.js shell with auth flow (signup, verify, login, MFA enroll); membership/roles; RLS enabled with test harness; CI (lint, typecheck, tests, tf plan); seed script.
**AC:** signup→org create→invite→accept works E2E in staging; RLS test matrix passes (cross-tenant read/write fails at API, DB, S3 layers); OpenAPI → generated TS client compiles; deploy pipeline green.

## Phase 1 — Vertical slice: upload → detect → review → export (single doc, one org)
Build: multipart upload + intake worker (validate, ClamAV, page split); extraction (PyMuPDF + Textract path + previews); deterministic detection (Presidio + Core PII starter pack, global exemption library seeded: federal + 5 states); manifest + candidates; review workspace v1 (viewer, overlay boxes, approve/reject with mandatory code, manual draw, keyboard shortcuts, complete-review checklist); export worker (clean PDF burn-in, metadata scrub, exemption log CSV/PDF); **integrity verifier as blocking gate**; audit events for the whole lifecycle; SSE progress.
**AC:** golden-file suite: 10 fixtures pass (recall ≥ 95% on Core PII set); 20-page born-digital doc upload→ready < 60 s in staging; export of doc with 25 redactions passes verifier; text extraction over every redacted region returns empty; approve without exemption code impossible (API + UI); every lifecycle event present in audit trail; demo script: upload sample police report → review → export in < 10 min.

## Phase 2 — Contextual AI + exemption citation engine
Build: Bedrock provider abstraction (zero-retention config, token accounting); contextual detection stage (chunking, grounded JSON output, hallucination guard, confidence mapping); AI justifications editable in review panel; Public Safety + HR + Legal starter packs with llm_context rules; merge/dedup + recurrence groups + "apply to all similar"; search-and-redact; compare view; annotated PDF export + redaction certificate; detector/prompt versions stamped and shown.
**AC:** golden set expands to 30 fixtures incl. narrative police report where victim/witness names are caught by context (not regex) with 7(C) citations; hallucinated-quote rate < 0.5% on golden runs (dropped + logged); justification present on 100% of LLM candidates; certificate verifies via public endpoint; annotated export shows codes; nightly canary accuracy job wired to metrics.

## Phase 3 — Teams & workflow
Build: requests (grouping), batch upload (ZIP), assignment + due dates, queues (my/team), supervisor dashboard, dual-approval flow (org policy), escalation, bulk candidate ops, low-confidence-first triage, email file parsing (.eml/.msg → request), DOCX intake, document timeline audit view, webhooks (document.ready, exported).
**AC:** 500-page batch completes < 20 min p95 with per-doc progress; dual-approval org cannot export without supervisor action (API-enforced); .eml with 3 attachments becomes reviewable request; queue filters/aging correct against seeded fixtures; concurrent reviewers on one document don't clobber (manifest If-Match verified by test).

## Phase 4 — Rules engine self-service
Build: rules workspace UI (packs, versions, editor drawers), org taxonomy management (clone from library), NL rule editing (LLM diff → confirm), manual upload → extraction → draft rules workspace → test bench → publish; exclusions engine; re-process with decision-preserving diff; suggested-rule-improvements report.
**AC:** NL instruction produces valid rule diff that round-trips the rules schema; publish is immutable (edit attempt creates new draft); test bench diff correct on fixtures; re-processing a reviewed doc preserves 100% of prior decisions on unchanged spans; extraction of a sample 20-page policy manual yields ≥ 10 sensible draft rules with source anchors (manual QA checklist).

## Phase 5 — Commercialization
Build: Stripe integration (plans, metered overage, invoicing/PO path, webhooks), usage dashboards + warnings, plan gates + pilot caps + conversion widgets, platform admin console (org lifecycle, flags, dashboards, support grants), marketing site (home, pricing, security/trust page with AI transparency downloads), onboarding polish (sample doc, checklists), data retention jobs + legal hold, org offboarding/export.
**AC:** self-serve card signup → Starter org processes doc → month-end invoice correct against usage_records (integration test with Stripe test clock); usage warnings fire at 80/95%; suspended org is read-only; platform admin cannot open document content (test); retention job deletes on schedule, respects legal hold; pilot→paid flip requires no migration.

## Phase 6 — Hardening & GA gate
Build/do: pentest remediation; load test to SLOs (k6: 200 concurrent orgs simulated); chaos pass on workers (kill mid-job → idempotent recovery, no lost usage records, no partial exports); accessibility audit fixes (WCAG 2.1 AA on review workspace + dashboard); SOC 2 evidence automation live; GovRAMP Snapshot submitted; disaster-recovery runbook + restore drill (RPO ≤ 24 h, RTO ≤ 8 h verified); on-call rotation + alarm tuning; docs site (user guide, API reference, security whitepaper).
**AC:** all SLOs met under load; restore drill documented; zero criticals from pentest open; DLQ chaos test: no cross-tenant or lost-data outcomes; trust page live with SOC 2 in-progress + Snapshot status.

## Post-GA roadmap (do not build now; keep architecture compatible)
Audio redaction (transcribe → redact → re-synthesize beeps) → video (frame detection) as separate metered job types; per-org email intake addresses; GovQA/NextRequest/JustFOIA integrations (be their redaction engine via API); state library expansion to all 50; SCIM; GovCloud environment for GovRAMP Authorized/FedRAMP 20x; requester portal only if customers pull hard.

## Risk register (watch during build)
| Risk | Mitigation |
|---|---|
| PDF burn-in edge cases (rotated pages, XFA forms, mixed raster/vector) | Integrity verifier as hard gate; edge-case corpus in golden suite; rasterize-region fallback |
| OCR quality on poor scans → missed content | Low-OCR-confidence page flags force manual attention; never mark such pages auto-complete |
| LLM cost blowout | Page-selection heuristics, chunk budget caps, per-org spend metering + alerts |
| Over-reliance on AI by reviewers | Completeness checklist, low-confidence gates, accuracy reporting honesty |
| Cross-tenant bug | RLS + CMK + tests at every layer; treat any near-miss as SEV-1 with public-postmortem discipline |
| Procurement stall | Pilot < P-card threshold, trust page, transparency artifacts ready before first pilot |
