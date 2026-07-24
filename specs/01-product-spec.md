# 01 — Product Specification

## Personas

| Persona | Role in app | Primary needs |
|---|---|---|
| **Reviewer / Records Analyst** (daily user) | Uploads, reviews AI candidates, edits redactions, exports | Speed, keyboard-driven review, confidence filters, clear reasons |
| **Supervisor** | QA, assignment, dual approval, workload visibility | Queue dashboards, low-confidence triage, override reports |
| **Agency Admin** | Org setup, users, rule packs, policies, retention | Easy invites, policy control, exemption library management |
| **Billing Admin** | Plan, usage, invoices | Usage transparency, invoice/PO workflow, CSV export |
| **Platform Admin** (RedactProof staff) | Tenant provisioning, plan/flag management, support | Metadata-only support access, usage across tenants, health |
| **Requester/Public** (indirect) | Receives exported records | Properly redacted, exemption log if released |

## Roles & permissions matrix

| Capability | Reviewer | Supervisor | Agency Admin | Billing Admin | Platform Admin |
|---|---|---|---|---|---|
| Upload & review documents | ✔ | ✔ | ✔ | — | — |
| Export final documents | ✔* | ✔ | ✔ | — | — |
| Assign work / manage queues | — | ✔ | ✔ | — | — |
| Approve (dual-approval orgs) | — | ✔ | ✔ | — | — |
| Manage rule packs & policies | propose | ✔ | ✔ | — | — |
| Manage users & roles | — | — | ✔ | — | — |
| View usage / billing / invoices | — | — | ✔ | ✔ | platform-wide |
| Tenant content access | own org | own org | own org | — | **never** (metadata-only; elevated mode is time-bound, customer-approved, fully logged) |

*If org policy `dual_approval_required` is on, Reviewer export is blocked until a Supervisor/Admin approves.

## Core user stories (v1, with acceptance criteria)

### Upload & processing
- **US-1** As a Reviewer, I drag-and-drop files (PDF, scanned PDF, PNG/JPG/TIFF, EML/MSG, DOCX, ZIP batch ≤ 2 GB) and see page-count estimate, selected rule pack, and usage impact before confirming. *AC: unsupported types rejected with clear message; malware-scanned; resumable multipart upload for >100 MB.*
- **US-2** As a Reviewer, I watch per-document progress (queued → extracting → detecting → ready) and can leave the page; state persists. *AC: SSE updates; batch shows per-item status.*
- **US-3** As a Reviewer, I can group documents into a **Request** (case) with a reference number so review and export happen as a package.

### AI redaction
- **US-4** As a Reviewer, when processing completes I see redaction candidates with: highlighted region, extracted text, exemption code + statute citation, plain-language justification, source rule, confidence (high/med/low). *AC: every candidate has all fields; low-confidence items filterable first.*
- **US-5** As an Agency Admin, I choose which rule packs run per upload (defaults set at org level). Org rules never affect any other org.

### Human review (the heart of the product)
- **US-6** As a Reviewer, I approve/reject candidates individually or in bulk ("accept all high-confidence"), with keyboard shortcuts (A approve, R reject, N next, arrows navigate). *AC: p95 action latency < 300 ms; all actions logged with actor+timestamp.*
- **US-7** As a Reviewer, I draw new redaction boxes (drag), select detected text spans, or search-and-redact all occurrences of a term/pattern across the document, choosing scope (this page / document / request).
- **US-8** As a Reviewer, every redaction I approve or create requires an exemption/reason code chosen from the org's active taxonomy; I can add a free-text note. *AC: approve button disabled until code selected; recently-used codes surfaced first.*
- **US-9** As a Reviewer, I toggle a compare view (original vs redaction preview) and see a completeness checklist before marking review complete (all low-confidence items addressed, all pages viewed).
- **US-10** As a Supervisor, I get an escalation queue of items reviewers flagged, and (if enabled) a dual-approval queue that blocks export until sign-off.
- **US-11** As a Reviewer, when I reject an AI candidate or add a manual redaction, the system records it as feedback; Admins see a "suggested rule improvements" report (v1: report only; no auto-learning).

### Export (user's explicit requirement)
- **US-12** As a Reviewer, I export the final redacted document with options: **(a) clean release version** — black boxes, no annotations; **(b) annotated version** — each box labeled with exemption code (and optional short reason) for internal use/training/court; **(c) exemption log** (PDF and CSV/JSON) listing every redaction: page, description, code, statute, justification, reviewer, timestamp; **(d) redaction certificate** — signed summary attesting destructive redaction, integrity verification pass, tool version, rule set versions. *AC: all four independently selectable; clean version passes integrity verifier; exports watermark-free.*
- **US-13** As a Reviewer, exported artifacts are retained per org retention policy, downloadable via short-lived signed URLs, and every download is audited.

### Org & team
- **US-14** As a new user, I self-serve: create account (email verify), create organization (name, jurisdiction/state, use case, est. volume), get suggested starter rule packs, and process my first document within 10 minutes — no sales call.
- **US-15** As an Agency Admin, I invite/deactivate users by email, assign roles, and see last-active. Seat counts reflect in billing.
- **US-16** As a Supervisor, I assign documents/requests to reviewers, set due dates, and see queue dashboards (new / processing / ready / in review / awaiting approval / completed) with aging.

### Policies & rules (see 06 for engine detail)
- **US-17** As an Agency Admin, I manage org rule packs: enable starter packs (Core PII, Public Safety, HR/Personnel, Legal Privilege, Health), customize the exemption taxonomy to my state, create custom rules via form or natural language ("redact witness cell numbers but not office switchboard numbers"), and publish versioned rule sets. *AC: processed documents permanently record rule set versions used.*
- **US-18** As an Agency Admin, I upload policy manuals/exemption guides; the system extracts draft rules with source references; nothing activates without my explicit publish.
- **US-19** As an Agency Admin, I test a draft rule set against sample documents (test bench) and see what would be caught before publishing.

### Audit & admin
- **US-20** As an Agency Admin, I search the org audit trail by document, user, action, date; export CSV. *AC: audit is append-only; includes upload, process, every candidate decision, exports, downloads, role changes, policy publishes, logins.*
- **US-21** As a Billing Admin, I see current-period usage (pages processed, OCR pages, documents, seats), plan allowance, projected overage, invoice history; download usage CSV. Warnings at 80%/95% of allowance; no hard cutoff without 7-day notice banner.
- **US-22** As a Platform Admin, I manage orgs (plan, feature flags, caps, suspend), view cross-tenant usage/health metrics, and use time-bound elevated support access (customer-approved, fully logged) — never silent content browsing.

## Workflows

1. **Quick Redact** (activation path): Upload → default pack preselected → process → review → export. Zero required setup.
2. **Batch**: multi-file/ZIP upload → rule pack + assignee → async processing → queue triage by confidence → per-doc or package export.
3. **Request package**: create Request → attach uploads/email files → review across documents with shared search-and-redact → export package (all clean docs + one combined exemption log).
4. **Email intake**: upload .eml/.msg → parse body + attachments into a Request → review as above. (Unique per-org intake address: Phase 5, flag-gated.)
5. **Manual → rules**: upload manual → extraction job → draft rules workspace → human accept/edit → test bench → publish version.
6. **Dual approval** (org policy): reviewer completes → supervisor approval queue → approve/return with notes → export unlocked.

## Explicitly out of scope (v1)

Video/audio redaction; public requester portal; deep RMS/ECM integrations (webhook + API enable partners instead); auto-learning rules from feedback (report only); mobile editing; on-prem.
