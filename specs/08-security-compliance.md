# 08 — Security & Compliance

Design target: pass a city/county security review and a police-department CJIS review on architecture alone, before any formal authorization exists. Certifications follow the roadmap in 00-overview; this file is what engineering builds.

## Tenant isolation (defense in depth)

| Layer | Control |
|---|---|
| API | JWT → membership check → `SET LOCAL app.org_id`; middleware rejects any handler executing without org context (except platform/public routes) |
| Database | RLS enabled + FORCED on all tenant tables; app role has no BYPASSRLS; migrations reviewed for policy coverage (CI check: every table with org_id must have a policy) |
| Storage | One content bucket, keys prefixed `{org_id}/`; bucket policy denies access without matching KMS grant; **per-org KMS CMK** — cryptographic isolation; signed URLs 5-min, single object, server-side ownership check first |
| Queues | Message schema requires org_id; workers set org context from message; DLQ triage cannot read content |
| Cache | Redis keys namespaced `org:{id}:`; no document content in Redis, ever |
| Logs/metrics | Content-free by construction; org_id tags for scoping |
| Cross-tenant tests | CI suite attempts cross-tenant reads at every layer; any pass = build failure. Attempted violations in prod → audit + alert |

## Encryption
- At rest: SSE-KMS everywhere (S3, Aurora, EBS, SQS); per-org CMKs for document content; annual rotation.
- In transit: TLS 1.2+ everywhere including intra-VPC service traffic.
- FIPS: use FIPS 140-3 validated modules/endpoints (AWS-LC, AWS FIPS endpoints) from day one — FIPS 140-2 certificates go Historical Sept 2026; CJIS/GovRAMP expect validated crypto.
- Field-level: `redaction_candidates.display_text` encrypted at application layer (envelope, org CMK) — the most sensitive strings in the DB.

## Identity & access
- MFA: TOTP available to all; FIDO2/WebAuthn supported; org policy can enforce MFA (default ON for new orgs). SMS OTP not offered (fails CJIS phishing-resistance direction).
- Enterprise SSO: per-org SAML/OIDC federation via Cognito; SCIM deferred.
- Sessions: 12h absolute / 1h idle default, org-configurable stricter; refresh rotation; revocation on role change/deactivation.
- Internal (staff) access: SSO + hardware keys; production access via break-glass with approval + session recording; no standing DB access to prod.

## Support access model (sellable trust feature)
- Default: platform admins see metadata only (org, job states, usage, errors) — never document content, candidate text, or previews.
- Elevated: customer Agency Admin approves a scoped, time-bound (≤ 24 h) grant; every access during grant writes customer-visible audit events; grants listed in the org's audit UI.
- No silent super-admin path exists in code — content endpoints check membership, not platform role.

## Audit integrity
- `audit_events` append-only, per-org SHA-256 hash chain (each row hashes canonical content + prev hash); nightly job verifies chains and anchors the day's head hash into a WORM-locked S3 object (Object Lock, compliance mode).
- Retention: ≥ 1 year hot (CJIS minimum), then Glacier; org data deletion never deletes audit rows (content-free by design).

## Data lifecycle
- Retention: org-configurable — uploads/originals (default 90 days post-export), exports (default 7 years), page previews follow originals. Legal-hold flag per document/request suspends deletion.
- Deletion: soft delete → scheduled S3 deletion + DB purge of content columns; certificate of deletion available. Org offboarding: full export package (documents, manifests, audit CSV) then destruction with attestation; per-org CMK scheduled for deletion (crypto-shred).
- Backups: Aurora PITR 35 days; S3 versioning + replication us-east-1→us-west-2 (both US). No data leaves the US; support staff US-based (CJIS/1075 posture).

## AI governance (procurement-ready answers)
- Inference: Amazon Bedrock, US regions, zero-retention config; contractual + technical: customer content never used to train any model (ours or providers').
- Transparency artifacts (kept in repo `/docs/ai-transparency/`): model inventory (model ids, versions, purpose), accuracy report (golden-set precision/recall, updated per release), bias testing summary (name-ethnicity and demographic-representation testing on detection recall), human-in-the-loop statement, data-flow diagram. These answer California EO N-5-26-style vendor certifications and local AI-policy reviews.
- Every candidate stores model + prompt version → any past decision is explainable.

## CJIS alignment checklist (v6.0-oriented, agreement-based — no central cert)
FIPS-validated encryption ✔ (above) · phishing-resistant MFA available + enforceable ✔ · audit logging 1-yr ✔ · personnel: background checks for staff with any content-adjacent access, security awareness training, fingerprinting per state agreements when required · incident response plan with CSA notification path · media sanitization (crypto-shred) ✔ · US-only ✔. Maintain a CJIS workbook mapping controls → evidence for agency reviews; be ready to sign CJIS Security Addenda per agency.

## Application security
- SSDLC: dependency scanning (Dependabot + pip-audit), SAST (Semgrep CI), container scanning (ECR), IaC scanning (tfsec), annual external pentest before GA, secrets scanning pre-commit.
- Upload handling: MIME sniffing, size caps, ClamAV, PDF parsing in sandboxed workers (no shell-outs on untrusted input), image decompression-bomb guards.
- WAF: managed rules + rate-based; CORS locked to app origins; strict CSP; no third-party scripts on app pages (analytics on marketing site only).
- Incident response: single runbook, severity matrix, customer notification target 24–72 h per contract (shortest-clock default), tabletop twice yearly.

## Compliance sequencing (engineering-relevant)
1. Now: build everything above; start SOC 2 Type II evidence collection (automation platform) from first prod deploy; GovRAMP Security Snapshot submission (top-40 NIST controls — architecture above covers them).
2. Month 6–18: SOC 2 Type II report; GovRAMP Ready (3PAO, ~80 controls); TX-RAMP L2 if Texas pipeline; HIPAA BAA capability (controls exist; add BAA template + PHI handling addendum).
3. Later: GovRAMP Authorized; FedRAMP 20x Moderate when federal demand justifies. Nothing in the stack blocks a GovCloud lift-and-shift.
