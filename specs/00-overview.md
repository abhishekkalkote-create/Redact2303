# 00 — Product Overview & Competitive Positioning

## Vision

The fastest trustworthy workspace for turning raw government records into defensible redacted outputs — AI does the first pass, humans stay in control, and every redaction carries a statutory citation and audit trail that survives litigation.

## Why now / market gaps (validated July 2026)

| Gap in market | Evidence | RedactProof answer |
|---|---|---|
| No context-aware exemption reasoning | All incumbents detect *patterns* (SSN regex, faces). None reason "this paragraph identifies a confidential informant → b(7)(D)" or cite the state statute | LLM contextual pass proposes exemption code + statute citation + draft justification per redaction |
| No modern cloud redaction at small-agency prices | Federal tools (FOIAXpress/Casepoint, Relativity, Nuix) are six figures; SLED platforms (GovQA, NextRequest, JustFOIA) bury shallow redaction as an add-on; cities <50k population still use Acrobat | Self-serve, published pricing; pilot tier under P-card threshold (<$10K/yr) |
| Distrusted pricing | CaseGuard markets "unlimited" with hidden 48K-page credit caps → refund disputes on Capterra; everything gov-focused is quote-based | Transparent plans, visible usage meter, no hidden caps, warning before limits |
| Slow batch performance | Top complaint across G2/Capterra: GovQA "incredibly slow", Redactable batch "takes forever", CaseGuard "failed on modest batches" | Performance SLOs in spec (see below); parallel page-level processing |
| Weak defensibility | Adobe has zero audit trail; most tools have logs but no exemption log or two-person review | Hash-chained audit trail, Vaughn-index-style exemption log, optional dual-approval workflow |
| Redaction integrity fears | AI inpainting now reconstructs improperly overlaid redactions — rising liability narrative | Destructive burn-in + automated integrity verifier + redaction certificate on every export |
| No gov-compliant AI story | Redactable: SOC 2 only, no gov cloud. CaseGuard: desktop. Veritone: FedRAMP but media-only, ~$95/hr pricing | CJIS-aligned architecture day one; Bedrock in-boundary inference, no-training attestation; SOC 2 → GovRAMP → FedRAMP 20x roadmap |

## Primary competitors (snapshot, mid-2026)

- **CaseGuard Studio** — all-media leader, desktop/on-prem, $279–379/user/mo, credit-cap trust issues, no FedRAMP/StateRAMP.
- **Redactable** — cloud docs-only, $19–99/mo per-doc tiers, SOC 2 + HIPAA, slow at volume, PDF/image formats only, no gov certs.
- **Veritone Redact** — FedRAMP video/audio, ~$95/hr of media, weak on documents.
- **Granicus GovQA / NextRequest (CivicPlus) / JustFOIA** — SLED request-management platforms; redaction shallow/add-on; GovQA notoriously slow.
- **OPEXUS FOIAXpress + Casepoint** (merged, Thoma Bravo) — federal incumbent, FedRAMP High, legacy UX, six-figure deals; post-merger churn is an opening.
- **Adobe Acrobat Pro** — the real status quo in small agencies; fully manual, no audit, no exemption codes.
- Others: Tyler/CSI Intellidact (courts/recorders, ecosystem-locked), Extract Systems (land records, legacy), ArkCase (FedRAMP FOIA case mgmt, services-heavy), Relativity Redact / Nuix (eDiscovery overkill).

## Positioning statement

For public-records and FOIA teams at state/local agencies, RedactProof is the AI redaction workspace that produces legally defensible redacted records in minutes instead of hours — unlike request-tracking platforms with bolt-on redaction or desktop tools with hidden caps, it combines context-aware AI, mandatory human review, per-redaction statutory citations, and a court-ready audit record, at published prices a records manager can buy on a P-card.

## Differentiators (ranked)

1. **Exemption citation engine** — two-level taxonomy (federal b(1)–b(9) incl. 7(A)–(F) subparts + per-state statute library), AI-drafted justifications, exportable exemption log. Greenfield; nobody does this.
2. **Defensibility as a product** — hash-chained audit, redaction certificate, integrity verifier, optional two-person approval, version-locked rule sets.
3. **Org-specific policy engine** — upload agency manuals/SOPs → extracted, versioned rule packs; natural-language rule editing; per-org, never shared.
4. **Honest, published pricing** with pilot tier under procurement thresholds.
5. **Speed** — first-session time-to-value < 10 minutes; batch SLOs below.
6. **Gov-grade trust posture from day one** — CJIS-aligned architecture, US-only, no-training AI, transparency one-pager for AI procurement reviews.

## Non-goals (v1)

- No video/audio redaction (architect the manifest/entity model so media types can be added; do not build).
- No full FOIA request-lifecycle management (intake portals, requester communication, appeals) — integrate with GovQA/NextRequest later instead of competing head-on.
- No on-premises deployment; no FedRAMP authorization work (keep GovCloud-portable).
- No auto-export without human review — permanently, as policy, not just v1.

## Performance SLOs (product requirements, tested in CI)

| Operation | Target |
|---|---|
| Single 20-page born-digital PDF: upload → candidates ready | < 60 s p95 |
| Single 20-page scanned PDF (OCR path) | < 3 min p95 |
| 500-page batch | < 20 min p95, per-document progress visible |
| Review workspace: page render, candidate accept/reject | < 300 ms p95 |
| Export 100-page redacted PDF + exemption log | < 90 s p95 |

## Success metrics

- Activation: new org completes upload→export in first session ≥ 60%.
- Accuracy: recall ≥ 95% on golden PII test set; reviewer-added (missed) redactions per 100 pages trending down.
- Efficiency: median reviewer time per page < 25% of manual baseline.
- Trust: zero cross-tenant incidents; zero integrity-verifier failures reaching customers.
- Commercial: pilot→paid conversion ≥ 40%; net revenue retention > 110%.

## Compliance & GTM roadmap (context for engineering decisions)

1. **Months 0–6:** SOC 2 Type II (automation platform e.g. Vanta/Drata); GovRAMP Security Snapshot; CJIS-aligned architecture (FIPS-validated crypto, phishing-resistant MFA, US-only personnel/support, 1-yr audit retention).
2. **Months 6–18:** GovRAMP Ready → Authorized as state deals demand; TX-RAMP Level 2 for Texas; HIPAA BAA capability.
3. **Later:** FedRAMP 20x Moderate when federal pipeline justifies (~$100–300K, 3–6 months under 2026 rules). Never bind to non-GovCloud-portable AWS services.
4. GTM: P-card pilots to city clerks/police records units → reseller/co-op access (Carahsoft/SHI, Sourcewell) → state term contracts.
