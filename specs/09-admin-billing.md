# 09 — Usage Metering, Billing & Administration

## Metering (internal truth)

Emitted as `usage_records` at processing time, idempotent by (job_id, metric):

| Metric | When | Notes |
|---|---|---|
| `pages_processed` | Extraction complete | Every page, both paths |
| `ocr_pages` | OCR path pages | Cost-tracking; also billable differentiator on high tiers |
| `llm_pages` | Pages sent to contextual pass | Internal cost only, not customer-billed |
| `documents` | Intake complete | Reporting |
| `exports` | Export succeeded | Reporting |
| `seats_active` | Daily snapshot of active members | Plan enforcement |

Internal unit-cost model per org (Textract, Bedrock tokens, compute) tracked for margin dashboards — customer pricing stays simple, our COGS visibility stays precise.

## Plans (published on marketing site — transparency is a differentiator)

| | **Pilot** | **Starter** | **Growth** | **Enterprise** |
|---|---|---|---|---|
| Price | $0 or $99 one-time, 60–90 days | **$299/mo** (annual $249/mo) | **$799/mo** (annual $665/mo) | Custom (annual PO) |
| Seats | 3 | 5 (extra $39) | 15 (extra $29) | Custom |
| Pages/mo | 1,000 total cap | 2,500 | 10,000 | Committed volume |
| Overage | Hard cap (upgrade prompt) | $12 / 100 pages | $9 / 100 pages | Committed + true-up |
| Features | Everything (time-boxed) | Core + batch | + Requests, dual approval, webhooks, priority support | + SSO/SAML, custom retention, dedicated onboarding, security review support, optional dedicated DB |
| Positioning | Under P-card thresholds | Small clerk teams; annual ≈ $3K | Police records units, counties; annual ≈ $8–10K — beats CaseGuard per-seat math by 3–5x for a 5-person team | State agencies, big cities |

Rules: no hidden caps — every limit visible on the usage page; warnings at 80%/95%; overage never silently blocks work mid-document (soft continue + invoice); prices honest and boring. Annual invoicing via PO/ACH supported on all paid tiers (agencies rarely use cards).

## Billing mechanics
- Stripe: subscription (plan) + metered overage item; daily job aggregates usage_records → Stripe meter events; month-end invoice. Net-30 invoicing path (Stripe Invoicing) for POs; card checkout for self-serve.
- Plan state machine: `trialing → active → past_due (14-day grace, banner) → suspended (read-only: can view/export nothing new, data intact 90 days) → canceled (offboarding flow)`. Pilot → paid = flag flip, same environment, no migration.
- All billing ops behind `app/billing/provider.py`; webhook handlers idempotent; Stripe is display-truth for invoices, our DB is truth for usage.

## Agency admin functionality (recap of surfaces; details in 01/07)
Users: invite by email, role assignment, deactivate (immediate session revocation), last-active; seat counts drive billing. Policies: dual approval, default packs, retention, MFA enforcement. Usage: meters, per-user table, CSV export, invoices.

## Platform admin (our staff)
- Org lifecycle: provision (sales-assisted), plan/flag/cap overrides, suspend/reactivate, offboard (export + destruction attestation).
- Dashboards: MRR/usage by org, margin per org (COGS model), SLO compliance, error/DLQ rates, LLM spend, golden-set accuracy trend.
- Support: metadata-only default; time-bound customer-approved elevated grants (08); impersonation does not exist.
- All platform actions audited to a platform audit log + customer-visible events where they touch an org.

## Pilot playbook (product-embedded)
- Pilot orgs: full features, page cap, banner showing cap progress + "equivalent value at Growth pricing", success-metrics widget (pages processed, est. hours saved @ configurable manual baseline, redactions by exemption).
- Day-75 in-app conversion prompt + export-able one-page ROI summary (PDF) the champion can hand to their director — designed artifact, not an afterthought.
