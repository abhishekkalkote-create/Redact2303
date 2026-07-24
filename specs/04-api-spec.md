# 04 — API Specification

Base: `https://api.redactproof.com/v1`. OpenAPI 3.1 is the contract (`/api/openapi.json`); the frontend consumes the generated TS client only.

## Conventions

- Auth: `Authorization: Bearer <Cognito JWT>`. Org context from membership; multi-org users (future) pass `X-Org-Id`.
- Errors: RFC 9457 problem+json: `{type, title, status, detail, instance, errors[]}`. Never leak other tenants' existence (404, not 403, for foreign IDs).
- Pagination: cursor-based `?cursor=&limit=` (max 100), response `{items, next_cursor}`.
- Idempotency: `Idempotency-Key` header honored on all POSTs that create jobs/exports.
- Rate limits: per-org token bucket; 429 with `Retry-After`. Upload endpoints excluded from low default limits.
- Versioning: path `/v1`; additive changes only within a version.

## Endpoints

### Auth & onboarding
```
POST   /auth/signup                     email, name, password → verify flow (Cognito-backed)
POST   /orgs                            create org {name, jurisdiction_state, org_type, use_case, est_monthly_pages}
GET    /orgs/current                    org profile + settings + plan + feature flags
PATCH  /orgs/current                    admin: settings (dual_approval, retention, export defaults)
POST   /orgs/current/invites            {email, role} → invite email
POST   /invites/{token}/accept
GET    /orgs/current/members            list; PATCH /members/{id} role/status (admin)
```

### Documents & requests
```
POST   /uploads                         init multipart {filename, size, mime, request_id?} → {upload_id, part_urls[]}
POST   /uploads/{id}/complete           finalize → creates document(s), enqueues intake; ZIP expands to N documents
GET    /documents                       filters: status, assignee, request_id, rule_pack, date range, q (name)
GET    /documents/{id}                  detail incl. status, pages, rule_set_version_ids, usage
PATCH  /documents/{id}                  assign, due_date, request_id
DELETE /documents/{id}                  soft delete (admin or uploader pre-review)
GET    /documents/{id}/pages/{n}/preview  short-lived signed URL for rendered page image
GET    /documents/{id}/events           SSE: processing progress + manifest change notifications
POST   /documents/{id}/process         {rule_pack_ids[]?, priority?} (re)run detection; re-run creates new candidates, keeps decisions on unchanged spans
POST   /requests                        {reference_no, title, due_date}; GET /requests; GET /requests/{id}
```

### Review (manifest operations; all mutations write review_actions + audit)
```
GET    /documents/{id}/manifest         full manifest: pages, candidates, completeness, version
POST   /documents/{id}/candidates       create manual candidate {page_no, bbox|text_span, exemption_code_id, note}
PATCH  /candidates/{id}                 {state: approved|rejected, exemption_code_id?, bbox?, note?} — If-Match manifest version
POST   /documents/{id}/candidates:bulk  {candidate_ids[]|filter{confidence,rule_key}, action, exemption_code_id?}
POST   /documents/{id}/search-redact    {query|pattern, scope: page|document|request, exemption_code_id} → creates approved candidates for all matches, returns list for confirm
POST   /documents/{id}/review:complete  validates completeness checklist → review_complete (or awaiting_approval)
POST   /documents/{id}/review:approve   supervisor dual-approval; :return {note} sends back
```

### Rules & taxonomy
```
GET    /exemption-codes                 org taxonomy (+ ?library=federal|state=WA to browse global library)
POST   /exemption-codes                 clone-from-library or create org code
GET    /rule-packs                      starter + org packs; POST /rule-packs
GET    /rule-packs/{id}/versions        ; POST /rule-packs/{id}/versions (new draft from current)
POST   /rule-set-versions/{id}/rules    create/edit rules while draft; PATCH/DELETE /rules/{id}
POST   /rule-set-versions/{id}/nl-edit  {instruction} → LLM-proposed rule diffs, returned as draft changes for confirm
POST   /rule-set-versions/{id}/test     {document_ids[]} → test-bench run: would-be candidates, diff vs current published
POST   /rule-set-versions/{id}/publish
POST   /manuals                         upload manual → extraction job; GET /manuals/{id}/draft-rules; POST /draft-rules/{id}:accept|:reject
```

### Export
```
POST   /documents/{id}/exports          {types: [clean_pdf, annotated_pdf, exemption_log_pdf, exemption_log_csv, exemption_log_json, certificate_pdf], annotated_options: {show_code: bool, show_label: bool}} → export job
POST   /requests/{id}/exports           package export: all docs clean + combined exemption log + certificate
GET    /exports/{id}                    status + integrity result; GET /exports/{id}/download → signed URL (audited)
GET    /documents/{id}/exports          history
```

### Usage, billing, audit
```
GET    /usage/current                   period totals by metric, allowance, projected overage, per-user breakdown
GET    /usage/records?period=           CSV/JSON export
GET    /billing/plan                    ; POST /billing/checkout (self-serve card) ; POST /billing/portal (Stripe portal)
GET    /billing/invoices
GET    /audit-events                    filters: actor, action, object_type/id, date range; CSV export
```

### Platform admin (separate subdomain admin.redactproof.com, separate Cognito app client, platform_admins only)
```
GET/POST/PATCH /platform/orgs           provision, plan changes, feature flags, caps, suspend
GET    /platform/usage                  cross-tenant metrics, health, SLO dashboards
POST   /platform/support-grants         request elevated access (requires customer approval flow); all use audited
```

## Webhooks (org-configurable, Phase 5)

`document.ready_for_review`, `document.exported`, `export.integrity_failed`, `usage.threshold_80/95` — HMAC-signed, retries with backoff.

## SSE events

`processing.progress {doc_id, stage, pages_done, pages_total}`, `manifest.updated {doc_id, version}`, `export.completed {export_id}`.
