# 03 — Data Model

IDs: ULID strings with type prefixes (`org_`, `usr_`, `doc_`, `cand_`, ...). All tables: `created_at`, `updated_at` timestamptz. All tenant tables carry `org_id` with RLS (policy: `org_id = current_setting('app.org_id')::text`). Audit tables are append-only (REVOKE UPDATE/DELETE).

## Entity relationship overview

```
organizations 1─* memberships *─1 users
organizations 1─* rule_packs 1─* rule_set_versions 1─* rules
organizations 1─* exemption_codes (org taxonomy, seeded from library)
organizations 1─* requests 1─* documents 1─* document_pages
documents 1─* processing_jobs
documents 1─1 manifests (current) ─* redaction_candidates ─* review_actions
documents 1─* export_artifacts
organizations 1─* usage_records, audit_events, invoices
manuals 1─* rule_extraction_jobs ─* draft_rules
```

## Tables (columns abridged to what matters; write full DDL in migrations)

### Identity & tenancy
- **organizations**: id, name, slug, jurisdiction_state (2-letter or 'FED'), org_type (police|city_clerk|county|state|school|other), plan (pilot|starter|growth|enterprise), plan_status (trialing|active|past_due|suspended), settings jsonb (`dual_approval_required` bool, `default_rule_pack_ids`, `retention_days_uploads`, `retention_days_exports`, `features` map, `export_defaults`), kms_key_arn, stripe_customer_id.
- **users**: id, cognito_sub unique, email, name, status (active|disabled), mfa_enrolled bool, last_active_at.
- **memberships**: org_id, user_id, role (reviewer|supervisor|agency_admin|billing_admin), status (invited|active|deactivated), invited_by. Unique(org_id, user_id). v1: user belongs to one active org (enforce in service layer, not schema).
- **platform_admins**: user_id, permissions jsonb. Not a membership; platform scope only.
- **support_access_grants**: id, org_id, granted_by (customer admin user), platform_user_id, scope (metadata|content), expires_at, reason. All use logged to audit_events.

### Rules & taxonomy (see 06 for semantics)
- **exemption_codes**: id, org_id (NULL = global library row), code ("b(7)(C)", "RCW 42.56.240(1)"), level (federal|state|org), state char(2) null, label, statute_citation, description, guidance_url, status (active|archived). Orgs clone library rows into org scope to customize.
- **rule_packs**: id, org_id (NULL = starter pack), name, description, category (core_pii|public_safety|hr|legal|health|custom), status.
- **rule_set_versions**: id, rule_pack_id, version int, status (draft|published|archived), published_by, published_at, changelog.
- **rules**: id, rule_set_version_id, rule_key (stable across versions, e.g. "PS-14"), name, trigger_type (regex|dictionary|entity|metadata|llm_context), pattern/config jsonb, exemption_code_id, priority int, confidence_policy (auto_high|suggest|flag_low), exclusions jsonb, scope (org|document_type|request), source_ref (manual section anchor), status.
- **manuals**: id, org_id, filename, s3_key, extraction_status; **draft_rules**: extraction output awaiting human accept/edit/reject, fields mirror rules + ai_notes, ambiguities.

### Documents & processing
- **requests**: id, org_id, reference_no, title, status (open|in_review|complete|closed), due_date, assignee_id.
- **documents**: id, org_id, request_id null, filename, mime_type, source (upload|email|batch), status — state machine: `uploaded → scanning → queued → extracting → detecting → ready_for_review → in_review → review_complete → awaiting_approval? → approved → exported | error | deleted`. page_count, ocr_used bool, rule_set_version_ids text[] (locked at processing), assignee_id, due_date, uploaded_by, s3_key_original, content_sha256, deleted_at (retention).
- **document_pages**: id, doc_id, org_id, page_no, s3_key_preview (rendered PNG), width, height, rotation, ocr_confidence numeric, has_text_layer bool.
- **processing_jobs**: id, org_id, doc_id, type (intake|extract|detect|export|verify|rule_extraction), status (queued|running|succeeded|failed|dead), attempt, started_at, ended_at, error jsonb, metrics jsonb (pages, tokens, ocr_pages).

### Review core
- **manifests**: id, doc_id unique, org_id, version int (bump on any change), schema_version, snapshot_s3_key (written at export), completeness jsonb (pages_viewed[], low_conf_resolved bool).
- **redaction_candidates**: id, org_id, doc_id, page_no, bbox jsonb {x,y,w,h, page coordinate space}, text_span jsonb {start,end,text_sha256} null, display_text (encrypted col, shown in UI), origin (deterministic|llm|manual|search_apply), source_rule_key null, source_rule_version null, exemption_code_id null (required to approve), ai_justification text, confidence (high|medium|low|n/a-manual), state — state machine: `suggested → approved | rejected | modified(→approved)`; manual candidates start `approved` intent but still require code. detector_versions jsonb {model_id, prompt_version, presidio_version}.
- **review_actions**: id, org_id, doc_id, candidate_id null, user_id, action (approve|reject|modify|create|bulk_approve|complete_review|approve_doc|return_doc|reopen), payload jsonb (before/after for modify), note, created_at. Append-only.

### Outputs, audit, billing
- **export_artifacts**: id, org_id, doc_id/request_id, type (clean_pdf|annotated_pdf|exemption_log_pdf|exemption_log_csv|exemption_log_json|certificate_pdf), s3_key, sha256, manifest_version, integrity_check jsonb {passed bool, checks[]}, created_by. Immutable.
- **audit_events**: id (ULID = time-ordered), org_id, actor_type (user|system|platform_admin), actor_id, action (enum ~40 values: document.uploaded, candidate.approved, export.downloaded, user.role_changed, ruleset.published, support_access.used, auth.login, ...), object_type, object_id, metadata jsonb (content-free), prev_hash, hash (SHA-256 of row canonical form + prev_hash — hash chain per org). Append-only; partitioned monthly; retained ≥ 1 year hot, then Glacier.
- **usage_records**: id, org_id, metric (pages_processed|ocr_pages|llm_pages|documents|exports|seats_active), quantity, doc_id null, job_id null, occurred_at, billing_period (YYYY-MM), reported_to_billing_at null. Emitted at processing completion; idempotency key (job_id, metric).
- **invoices**: mirror of Stripe invoice state for display; org_id, period, line_items jsonb, status, pdf_url.

## State machine rules (enforce in service layer + DB constraints)

- `documents.status = exported` requires: ≥1 review_actions `complete_review`, zero candidates in `suggested` with confidence=low unresolved, (if org dual_approval) an `approve_doc` action by supervisor/admin, and an export_artifact whose integrity_check.passed = true.
- `redaction_candidates.state = approved` requires exemption_code_id NOT NULL (DB CHECK).
- rule_set_versions immutable once published; edits create the next draft version.
- Deleting a document = soft delete + scheduled S3 object deletion per retention; audit rows are never deleted.

## RLS test matrix (CI-mandatory)

For each tenant table: user of org A attempting SELECT/INSERT/UPDATE on org B rows → 0 rows / error. Worker with org A context reading org B S3 key → denied (bucket policy scoping by KMS grant + prefix conditions). Signed URL for org A object requested by org B session → 403.
