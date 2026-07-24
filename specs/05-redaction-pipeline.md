# 05 — Redaction Pipeline

Seven stages, each an idempotent worker consuming SQS. Every stage records metrics to `processing_jobs.metrics` and emits usage records where noted.

## Stage 1: Intake
- Validate: size ≤ 2 GB (ZIP) / 500 MB (single), MIME sniff (not extension trust), page-count estimate, corruption check.
- Malware scan (ClamAV container); infected → `error` with audit event, file quarantined.
- ZIP: expand to child documents (flatten one level; nested zips rejected). EML/MSG: parse headers/body/attachments into a Request with child documents (body rendered to PDF).
- DOCX: convert to PDF (LibreOffice headless) — the PDF is the working artifact; original retained.
- Store original at `s3://{content-bucket}/{org_id}/originals/{doc_id}` (SSE-KMS with org key). Compute `content_sha256`.

## Stage 2: Extraction
- Born-digital PDF (has text layer): PyMuPDF extracts text spans with coordinates per page. Cheap path.
- Scanned/image pages: Textract (async API for multi-page) → blocks with geometry + confidence; Tesseract fallback if Textract errors. Record per-page `ocr_confidence`; pages < 0.6 flagged in UI ("low OCR quality — review manually").
- Render page previews (PNG @ 150 DPI) to `{org_id}/previews/{doc_id}/{page}.png`.
- Canonical coordinate space: PDF points, origin top-left, rotation normalized. All bboxes everywhere use this space.
- Emit usage: `pages_processed` (all), `ocr_pages` (OCR path only).

## Stage 3: Deterministic detection
- Engine: Microsoft Presidio (NER + validators) + org rule set compiled matchers (regex, dictionaries, checksum validators for SSN/CC/routing numbers).
- Runs per page batch (10 pages) in parallel. Output: candidates with `origin=deterministic`, `source_rule_key`, rule's exemption code, confidence from rule's `confidence_policy`.
- Deterministic-only findings are never auto-approved; `auto_high` policy only preselects in UI.

## Stage 4: Contextual LLM detection
- Selection: pages containing narrative text (not just forms/tables), pages where deterministic pass found seed entities needing context (names → is this a victim/witness/juvenile?), and rules with `trigger_type=llm_context`.
- Chunking: semantic blocks (paragraph-level with 1-page overlap window), max ~4K tokens per call.
- Prompt (versioned in repo `workers/detect/prompts/contextual_v{N}.md`): inputs = chunk text + active org rules (llm_context ones) + org exemption taxonomy summary + document type. Output = strict JSON: `{findings: [{quote, char_offsets, entity_kind, exemption_code, confidence: 0-1, justification (≤ 240 chars, plain language, cites why the exemption applies)}]}`.
- Grounding: model quote must string-match extracted text (fuzzy ≥ 0.95) or the finding is dropped and logged (hallucination counter metric). Offsets mapped back to page bboxes via span index.
- Bedrock config: zero data retention, no training (attested), us-region inference profile, model id + prompt version stamped on every candidate. Token usage → `llm_pages` usage metric + per-org cost accounting.
- Confidence mapping: ≥0.85 high, 0.6–0.85 medium, <0.6 low.

## Stage 5: Merge & manifest
- Deduplicate overlapping candidates (IoU > 0.5 or identical span): keep union bbox; prefer more-specific exemption code; record both sources in `detector_versions`.
- Conflicting exemption codes on same span → keep both as alternatives; UI shows picker, medium confidence max.
- Cross-page recurrence: identical text spans grouped (`recurrence_group_id`) to power "apply to all similar".
- Write manifest v1, set document `ready_for_review`, notify SSE + optional webhook.

## Stage 6: Export (burn-in)
Rendered exclusively from the manifest snapshot (approved candidates only).
1. **Clean PDF:** PyMuPDF `add_redact_annot` + `apply_redactions()` per approved bbox — this deletes underlying text/image content, then draws black box. For OCR'd scans: also rasterize affected region to guarantee pixel removal.
2. **Metadata scrub (pikepdf):** strip XMP/DocInfo, embedded files, JavaScript, hidden layers (OCGs flattened), annotations, form fields (flatten), bookmarks referencing redacted content.
3. **Annotated PDF:** same burn-in, plus label per box: exemption code (and label if `show_label`), 6pt white-on-black in box corner.
4. **Exemption log:** PDF + CSV + JSON. Per redaction: seq #, page, region descriptor, exemption code, statute citation, justification (AI-drafted, reviewer-edited), source rule + version, reviewer, decided_at. Header: document name+hash, org, rule set versions, reviewers, export time, tool version. This is Vaughn-index-ready.
5. **Redaction certificate:** one-pager attesting destructive redaction performed, integrity verification passed, counts by exemption, hash of clean PDF, manifest version, detector versions. Signed (SHA-256 + our signing key; verification endpoint public).

## Stage 7: Integrity verification (blocking gate)
Runs on every clean/annotated export before it is stored as downloadable:
1. Re-extract text over every redacted bbox (PyMuPDF) → must be empty.
2. Full-document text search for every redacted span's exact text (and normalized variants: case, whitespace, hyphenation) → zero hits outside approved-visible context.
3. Metadata scan: DocInfo/XMP/embedded objects empty of scrubbed fields; no JS; no attachments.
4. Render-and-diff spot check: rasterize redacted regions → verify uniform fill (no ghost pixels beneath).
Failure → export blocked, `export.integrity_failed`, on-call paged, incident audit event. This gate is what the redaction certificate attests.

## Re-processing & rule upgrades
Re-running detection (new rule set version) diffs against existing manifest: candidates whose span+rule unchanged keep their decision; new findings arrive as `suggested`; removed rules leave decided candidates untouched (flagged "source rule archived"). Document permanently records every rule set version used.

## Feedback loop (v1 = report only)
Nightly job aggregates: rejected AI candidates by rule/pattern, reviewer-added manual redactions clustered by text pattern → "suggested rule improvements" report for admins. No automatic rule mutation.

## Golden-file test suite (CI)
`/tests/pipeline/golden/`: ~30 fixture documents (synthetic: police report, HR file, email chain, poor scan, rotated pages, forms) each with expected-manifest JSON. Detection changes must keep recall ≥ 95% / precision ≥ 80% on the golden set; export tests assert integrity verifier passes and text-over-boxes is empty.
