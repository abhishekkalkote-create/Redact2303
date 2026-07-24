# 07 — UI Specification

Stack: Next.js App Router, Tailwind, shadcn/ui, PDF.js viewer, TanStack Query + generated API client. Desktop-first (analyst tool); readable on tablet; no mobile editing.

## Design standards
- Clean enterprise aesthetic; restrained neutral palette; color used semantically only: suggested (amber outline), approved (solid black w/ green check chip), rejected (gray strikethrough), manual (blue outline), low-confidence (red badge), error (red).
- Selected candidate's exemption code, statute, justification, source rule, confidence always visible in the side panel — never behind a modal.
- Keyboard-first review; visible shortcut hints; command palette (⌘K) for navigation.
- Every destructive/irreversible action confirms with consequence text ("Export burns redactions permanently").
- WCAG 2.1 AA (gov buyers check); full audit-friendly empty/error states.

## Screens

### 1. Auth & onboarding
Signup → email verify → "Create your organization" (name, state/jurisdiction dropdown, org type, use case, est. volume) → starter pack suggestions pre-checked by org type → land on Dashboard with a "Upload your first document" hero + optional sample document to try instantly (demo doc processes free, exemplifies exemption citations). Invite teammates step skippable.

### 2. Dashboard / queues
- Header: org name, quick upload button, search, user menu. Left nav: Dashboard, Documents, Requests, Rules & Policies, Audit, Usage & Billing (role-gated), Settings.
- KPI row: New / Processing / Ready for review / In review / Awaiting approval / Completed this month.
- Tabs: **My queue** (assigned to me, sorted low-confidence-first option) | **Team queue** (supervisor: per-reviewer workload, aging, due dates) | **Recent exports**.
- Table columns: name, request #, status chip, pages, confidence profile (mini bar: high/med/low counts), assignee, due, updated. Row → review workspace. Bulk actions: assign, set due, add to request.

### 3. Upload modal / page
Drag-drop zone (multi-file, folder, ZIP; shows accepted types), then per-file: detected type, est. pages. Options panel: rule packs (org defaults pre-checked, chips with tooltips), assign to, request (existing/new), priority. Footer: "≈ 137 pages will count toward your allowance (2,480 remaining)". Buttons: Process now / Save as draft. After submit: inline per-file progress list; safe to navigate away.

### 4. Review workspace (the product)
```
┌ Top bar: doc name · status chip · assignee · manifest v · [Complete review] [Export ▾] ┐
├─ Left rail (240px): page thumbnails w/ candidate-count badges; filters:               │
│    confidence (low first), state, exemption code, origin (AI/manual); progress ring   │
├─ Center: PDF.js viewer, virtualized pages, zoom/fit, rotate view;                     │
│    candidates as overlay boxes (semantic colors); drag-to-draw new box;               │
│    text-select → "Redact selection…"; right-click → apply to all similar (N found)    │
├─ Right panel (360px):                                                                 │
│    Candidate card: extracted text (blurred until hover) · confidence badge ·          │
│    exemption code picker (searchable, recent-first, shows statute + guidance) ·       │
│    AI justification (editable textarea) · source rule + version link · notes ·        │
│    [Approve] [Reject] [Escalate]; recurrence strip: "appears on 6 pages [Review all]" │
│    Below: candidate list (virtualized) synced to viewer scroll                        │
└ Footer bar: shortcuts hint (A approve · R reject · N next · ⇧A approve-all-visible ·  │
     C compare) · completeness meter ("3 low-confidence remaining · 2 pages unviewed")  ┘
```
- **Compare mode (C):** splits center into original | redaction preview, synced scroll.
- **Search & redact:** top-bar search field → matches list with page context → select all/some → pick code → creates approved candidates; confirmation step always.
- **Complete review** validates checklist (all pages viewed, low-confidence resolved) → status advances (or to approval queue). Blocking items are clickable.

### 5. Export dialog
Checkboxes: Clean release PDF (default ✔) · Annotated PDF (sub-options: show code / show label) · Exemption log (PDF/CSV/JSON) · Redaction certificate. Summary: N redactions across M pages, counts by exemption code. Warning copy about permanence. Progress → artifact list with download buttons + SHA-256, integrity check ✔ badge. History tab per document.

### 6. Rules & Policies workspace
- Left nav: Starter packs · Org rule packs · Exemption taxonomy · Manuals · Draft extracts.
- Rule pack view: version selector, tabs Rules | Test bench | Versions | Source docs. Rules table: key, name, trigger type, exemption code, priority, confidence policy, exclusions count, status. Rule editor drawer: form-based per trigger type + NL edit box ("Describe the change…") producing a reviewable diff.
- Taxonomy view: tree grouped federal/state/org; clone-from-library flow; usage counts per code.
- Manual extraction: upload → progress → draft rules table with per-rule accept/edit/reject, ai ambiguity notes, source quote popover → "Add N accepted to draft version".
- Test bench: pick sample docs → run → results as would-be candidates with diff vs published (added/removed) and exclusion hits.

### 7. Audit
Filterable event stream (actor, action, object, date). Document timeline view: vertical lifecycle from upload to export with actors. Export CSV. Hash-chain verification status indicator.

### 8. Usage & Billing
Plan card (name, seats, included pages, renewal). Usage meters: pages processed / OCR pages / documents / active seats, with 80%/95% warning states and projected overage in $. Usage-by-user table. Invoices list (status, PDF). Buttons: Upgrade plan (self-serve tiers with published prices), Contact sales (Enterprise), Export usage CSV. Pilot orgs see: pilot cap progress + "equivalent paid value" framing + convert CTA.

### 9. Org settings
General (name, jurisdiction) · Members (invite, role, deactivate, last active) · Policies (dual approval toggle, default rule packs, retention sliders for uploads/exports with legal-hold note, export defaults) · Security (SSO config Enterprise-only, MFA enforcement toggle, session length) · API & webhooks (Phase 5).

### 10. Platform admin console (admin.redactproof.com, separate app)
Org list (plan, status, usage, health), org detail (flags, caps, plan override, suspend), cross-tenant dashboards (SLOs, queue depth, LLM spend), support access requests (request → customer-approval state → time-bound grant), audit of all platform-admin actions. Deliberately utilitarian.

### 11. Marketing site (separate, static)
Home (promise + 2-min demo video + published pricing table), Security & Trust page (architecture, CJIS alignment, SOC 2/GovRAMP status, AI transparency one-pager download, no-training attestation), Pricing, Docs. Trust page is a sales asset for gov security reviewers — keep it current.
