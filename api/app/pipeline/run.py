"""Orchestrates specs/05-redaction-pipeline.md Stages 2-5 (extraction through manifest)
for one document. Phase 1 simplification, stated plainly: this runs synchronously in the
API process rather than as separate SQS-consumed Fargate workers (infra/modules/queues
already provisions the queues; nothing consumes them yet — that's real async-worker
plumbing appropriate once a staging environment exists to deploy workers into). The
function boundaries here (extract/detect are separate, idempotent-per-page steps) are
shaped so lifting them into real workers later is a wiring change, not a rewrite.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.llm.provider import LLMProvider, get_provider
from app.models.document import Document, DocumentPage
from app.models.manifest import Manifest
from app.models.processing_job import ProcessingJob
from app.models.redaction_candidate import RedactionCandidate
from app.models.rule import Rule
from app.models.usage_record import UsageRecord
from app.pipeline.detect import detect_page, get_active_rules
from app.pipeline.detect_llm import detect_page_contextual
from app.pipeline.extract import PageExtraction, extract_pdf
from app.pipeline.merge import MergeInput, group_recurrence, merge_overlapping
from app.services.audit_service import write_audit_event
from app.services.webhook_service import trigger_event
from app.storage import get_store

# specs/03-data-model.md documents state machine — reprocessing re-runs detection only
# (content is unchanged), so it's only meaningful once a document has been extracted at
# least once, and never on a document whose export is already final or that's mid-flight
# through another stage of its own.
_NOT_REPROCESSABLE_STATUSES = ("uploaded", "scanning", "queued", "extracting", "detecting", "exported", "deleted")


async def _record_usage(session: AsyncSession, org_id: str, metric: str, quantity: int, doc_id: str, job_id: str) -> None:
    now = datetime.now(UTC)
    session.add(
        UsageRecord(
            id=new_id("use"), org_id=org_id, metric=metric, quantity=quantity,
            doc_id=doc_id, job_id=job_id, occurred_at=now, billing_period=now.strftime("%Y-%m"),
        )
    )


async def _merge_and_group(
    session: AsyncSession, org_id: str, all_candidates: list[RedactionCandidate]
) -> list[RedactionCandidate]:
    """specs/05-redaction-pipeline.md Stage 5: dedupe overlapping candidates (deterministic
    + LLM may both flag the same span) and group cross-page recurrences. Mutates/deletes
    candidates in `session` directly; `all_candidates` must already be flushed (have ids).
    Returns the survivors (i.e. `all_candidates` minus whichever were dropped as
    duplicates) — reprocess_document() needs this to diff against a document's existing
    candidates by identity without touching now-deleted ORM instances."""
    cipher = get_cipher()
    merge_inputs = [
        MergeInput(
            key=c.id, page_no=c.page_no, bbox=c.bbox, origin=c.origin,
            exemption_code_id=c.exemption_code_id, confidence=c.confidence,
            detector_versions=c.detector_versions, text=cipher.decrypt(org_id, c.display_text_encrypted),
        )
        for c in all_candidates
    ]
    by_id = {c.id: c for c in all_candidates}

    for group in merge_overlapping(merge_inputs):
        kept = by_id[group.kept_key]
        if group.bbox is not None:
            kept.bbox = group.bbox
        if group.detector_versions_update is not None:
            kept.detector_versions = group.detector_versions_update
        for dropped_key in group.dropped_keys:
            await session.delete(by_id[dropped_key])
            del by_id[dropped_key]

    remaining_inputs = [mi for mi in merge_inputs if mi.key in by_id]
    for key, recurrence_group_id in group_recurrence(remaining_inputs).items():
        by_id[key].recurrence_group_id = recurrence_group_id

    await session.flush()
    return list(by_id.values())


async def _detect_all_pages(
    session: AsyncSession,
    provider: LLMProvider,
    org_id: str,
    doc_id: str,
    pages: list[PageExtraction],
    active_rules: list[Rule],
    version_number_by_rsv_id: dict[str, int],
) -> tuple[list[RedactionCandidate], int, int, int, int]:
    """The deterministic + contextual detection passes over every page — shared by the
    initial process_document() run and reprocess_document()'s fresh detection pass.
    Returns (candidates, hallucinated_findings, llm_input_tokens, llm_output_tokens,
    llm_pages_used)."""
    all_candidates: list[RedactionCandidate] = []
    total_hallucinated = 0
    total_llm_input_tokens = 0
    total_llm_output_tokens = 0
    llm_pages_used = 0

    for page in pages:
        deterministic = await detect_page(session, org_id, doc_id, page, active_rules, version_number_by_rsv_id)
        all_candidates.extend(deterministic)

        # specs/05-redaction-pipeline.md Stage 4 selection: only pages with narrative text
        # get the (comparatively expensive) contextual pass — skip pages with no text layer.
        if page.has_text_layer:
            llm_candidates, hallucinated, in_tok, out_tok = await detect_page_contextual(
                session, provider, org_id, doc_id, page
            )
            all_candidates.extend(llm_candidates)
            total_hallucinated += hallucinated
            total_llm_input_tokens += in_tok
            total_llm_output_tokens += out_tok
            if llm_candidates or in_tok:
                llm_pages_used += 1

    return all_candidates, total_hallucinated, total_llm_input_tokens, total_llm_output_tokens, llm_pages_used


def _candidate_identity_key(candidate: RedactionCandidate) -> tuple[int, int, int] | None:
    """Stable identity for a detected span across detection runs — the same underlying
    PDF text always re-extracts to the same (page_no, start, end), so this is exact, not
    fuzzy. Only deterministic/llm-origin candidates participate: manual and search_apply
    candidates are human-authored, not detection output, so a re-run must never match,
    refresh, or delete them."""
    if candidate.origin not in ("deterministic", "llm") or candidate.text_span is None:
        return None
    return (candidate.page_no, candidate.text_span["start"], candidate.text_span["end"])


async def reprocess_document(
    session: AsyncSession, org_id: str, doc_id: str, actor_id: str, rule_pack_ids: list[str] | None = None
) -> Manifest:
    """specs/04-api-spec.md: POST /documents/{id}/process "(re)run detection; re-run
    creates new candidates, keeps decisions on unchanged spans." Re-extracts page text
    in-memory only (the source PDF is unchanged, so this never touches document_pages or
    previews) to get fresh PageExtraction data, runs the same detection passes as the
    initial run, then diffs the fresh candidates against the document's existing ones by
    `_candidate_identity_key`:
      - span matched in both passes, old row still `suggested` (never decided): its
        detection metadata (bbox, source_rule_key, version, origin, confidence,
        ai_justification, detector_versions) is refreshed from the new pass — nothing to
        lose yet, so taking the fresher detection is strictly better. Preserves the row's
        id (and any review_actions already referencing it) rather than minting a new one.
      - span matched in both passes, old row already decided (approved/rejected/modified):
        left completely untouched — not even detection metadata — since a reviewer may
        have hand-adjusted its bbox or justification, and a rule/detector change must
        never silently overwrite that edit. Only the redundant new-pass duplicate is
        discarded.
      - span only in the new pass: a genuinely new `suggested` candidate.
      - span only in the old pass and still `suggested` (never decided): dropped.
      - span only in the old pass but already decided: kept as-is — a human decision is
        never silently discarded just because a rule change stopped re-detecting it.
    """
    document = await session.get(Document, doc_id)
    assert document is not None
    if document.status in _NOT_REPROCESSABLE_STATUSES:
        raise ApiError(422, "Unprocessable Entity", f"Document cannot be reprocessed from status: {document.status}")

    existing_result = await session.execute(select(RedactionCandidate).where(RedactionCandidate.doc_id == doc_id))
    existing_by_key: dict[tuple[int, int, int], RedactionCandidate] = {}
    for candidate in existing_result.scalars().all():
        key = _candidate_identity_key(candidate)
        if key is not None:
            existing_by_key[key] = candidate

    store = get_store()
    assert document.s3_key_original is not None, "document has no stored original to reprocess"
    original_bytes = store.get(org_id, document.s3_key_original)
    pages = extract_pdf(original_bytes)

    document.status = "detecting"
    detect_job = ProcessingJob(id=new_id("job"), org_id=org_id, doc_id=doc_id, type="detect", status="running", started_at=datetime.now(UTC), attempt=1)
    session.add(detect_job)
    await session.flush()

    active_rules, version_number_by_rsv_id, rule_set_version_ids = await get_active_rules(session, org_id, rule_pack_ids)
    document.rule_set_version_ids = rule_set_version_ids

    provider = get_provider()
    new_candidates, total_hallucinated, in_tok, out_tok, llm_pages_used = await _detect_all_pages(
        session, provider, org_id, doc_id, pages, active_rules, version_number_by_rsv_id
    )
    await session.flush()  # candidates need ids before merge can reference them
    new_candidates = await _merge_and_group(session, org_id, new_candidates)

    preserved, created, dropped = 0, 0, 0
    matched_existing_keys: set[tuple[int, int, int]] = set()
    for new_candidate in new_candidates:
        key = _candidate_identity_key(new_candidate)
        old_candidate = existing_by_key.get(key) if key is not None else None
        if key is None or old_candidate is None:
            created += 1
            continue

        matched_existing_keys.add(key)
        if old_candidate.state == "suggested":
            old_candidate.bbox = new_candidate.bbox
            old_candidate.origin = new_candidate.origin
            old_candidate.source_rule_key = new_candidate.source_rule_key
            old_candidate.source_rule_version = new_candidate.source_rule_version
            old_candidate.confidence = new_candidate.confidence
            old_candidate.ai_justification = new_candidate.ai_justification
            old_candidate.detector_versions = new_candidate.detector_versions
        # else: already decided — left untouched (see docstring). Either way the
        # freshly-detected duplicate row is discarded; the old id survives.
        await session.delete(new_candidate)
        preserved += 1

    for key, old_candidate in existing_by_key.items():
        if key in matched_existing_keys:
            continue
        if old_candidate.state == "suggested":
            await session.delete(old_candidate)
            dropped += 1
        # else: already decided, no longer re-detected — kept as-is.

    await session.flush()

    detect_job.status = "succeeded"
    detect_job.ended_at = datetime.now(UTC)
    detect_job.metrics = {
        "candidates_created": created, "candidates_preserved": preserved, "candidates_dropped": dropped,
        "hallucinated_findings": total_hallucinated, "llm_input_tokens": in_tok, "llm_output_tokens": out_tok,
    }
    if llm_pages_used:
        await _record_usage(session, org_id, "llm_pages", llm_pages_used, doc_id, detect_job.id)

    manifest_result = await session.execute(select(Manifest).where(Manifest.doc_id == doc_id))
    manifest = manifest_result.scalars().one()
    manifest.version += 1

    document.status = "ready_for_review"
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=actor_id,
        action="document.reprocessed", object_type="document", object_id=doc_id,
        metadata={"candidates_created": created, "candidates_preserved": preserved, "candidates_dropped": dropped},
    )
    await trigger_event(
        session, org_id, "document.ready_for_review",
        {"doc_id": doc_id, "pages": len(pages), "candidates_created": created},
    )
    await session.flush()
    await session.refresh(manifest)
    return manifest


async def process_document(session: AsyncSession, org_id: str, doc_id: str, actor_id: str, bill_usage: bool = True) -> Manifest:
    """`session` must be org-scoped (app.org_id = org_id). Raises on failure — caller is
    responsible for marking the document `error` and writing the failure audit event
    (see app/routers/documents.py), since only it knows the original exception context.

    bill_usage=False for the onboarding sample document (app/routers/documents.py's
    POST /documents/sample) — specs/07-ui-spec.md: "demo doc processes free.\""""
    store = get_store()
    document = await session.get(Document, doc_id)
    assert document is not None

    document.status = "extracting"
    extract_job = ProcessingJob(id=new_id("job"), org_id=org_id, doc_id=doc_id, type="extract", status="running", started_at=datetime.now(UTC), attempt=1)
    session.add(extract_job)
    await session.flush()
    await write_audit_event(
        session, org_id=org_id, actor_type="system", actor_id=actor_id,
        action="document.processing_started", object_type="document", object_id=doc_id,
        metadata={"stage": "extract"},
    )

    assert document.s3_key_original is not None, "document has no stored original to process"
    original_bytes = store.get(org_id, document.s3_key_original)
    pages = extract_pdf(original_bytes)

    ocr_page_count = 0
    for page in pages:
        preview_key = f"previews/{doc_id}/{page.page_no}.png"
        store.put(org_id, preview_key, page.preview_png)
        session.add(
            DocumentPage(
                id=new_id("pg"), doc_id=doc_id, org_id=org_id, page_no=page.page_no,
                s3_key_preview=preview_key, width=page.width, height=page.height,
                rotation=page.rotation, has_text_layer=page.has_text_layer,
                ocr_confidence=page.ocr_confidence,
            )
        )
        if page.ocr_confidence is not None:
            ocr_page_count += 1

    document.page_count = len(pages)
    document.ocr_used = ocr_page_count > 0
    extract_job.status = "succeeded"
    extract_job.ended_at = datetime.now(UTC)
    extract_job.metrics = {"pages": len(pages), "ocr_pages": ocr_page_count}
    if bill_usage:
        await _record_usage(session, org_id, "pages_processed", len(pages), doc_id, extract_job.id)
        if ocr_page_count:
            await _record_usage(session, org_id, "ocr_pages", ocr_page_count, doc_id, extract_job.id)
    await session.flush()

    document.status = "detecting"
    detect_job = ProcessingJob(id=new_id("job"), org_id=org_id, doc_id=doc_id, type="detect", status="running", started_at=datetime.now(UTC), attempt=1)
    session.add(detect_job)
    await session.flush()

    # specs/03-data-model.md: rule_set_version_ids "locked at processing" — resolved once
    # per document, not once per page.
    active_rules, version_number_by_rsv_id, rule_set_version_ids = await get_active_rules(session, org_id)
    document.rule_set_version_ids = rule_set_version_ids

    provider = get_provider()
    all_candidates, total_hallucinated, total_llm_input_tokens, total_llm_output_tokens, llm_pages_used = (
        await _detect_all_pages(session, provider, org_id, doc_id, pages, active_rules, version_number_by_rsv_id)
    )

    await session.flush()  # candidates need ids before merge can reference them
    await _merge_and_group(session, org_id, all_candidates)
    total_candidates = len(all_candidates)  # includes any later deleted by merge; job metric is pre-merge volume for visibility

    detect_job.status = "succeeded"
    detect_job.ended_at = datetime.now(UTC)
    detect_job.metrics = {
        "candidates": total_candidates,
        "hallucinated_findings": total_hallucinated,
        "llm_input_tokens": total_llm_input_tokens,
        "llm_output_tokens": total_llm_output_tokens,
    }
    if llm_pages_used and bill_usage:
        await _record_usage(session, org_id, "llm_pages", llm_pages_used, doc_id, detect_job.id)
    await session.flush()

    manifest = Manifest(id=new_id("man"), doc_id=doc_id, org_id=org_id, version=1)
    session.add(manifest)

    document.status = "ready_for_review"
    await write_audit_event(
        session, org_id=org_id, actor_type="system", actor_id=actor_id,
        action="document.ready_for_review", object_type="document", object_id=doc_id,
        metadata={"pages": len(pages), "candidates": total_candidates, "hallucinated_findings": total_hallucinated},
    )
    await trigger_event(
        session, org_id, "document.ready_for_review",
        {"doc_id": doc_id, "pages": len(pages), "candidates": total_candidates},
    )
    await session.flush()
    await session.refresh(manifest)
    return manifest
