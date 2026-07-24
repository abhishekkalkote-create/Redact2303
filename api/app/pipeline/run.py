"""Orchestrates specs/05-redaction-pipeline.md Stages 2-5 (extraction through manifest)
for one document. Phase 1 simplification, stated plainly: this runs synchronously in the
API process rather than as separate SQS-consumed Fargate workers (infra/modules/queues
already provisions the queues; nothing consumes them yet — that's real async-worker
plumbing appropriate once a staging environment exists to deploy workers into). The
function boundaries here (extract/detect are separate, idempotent-per-page steps) are
shaped so lifting them into real workers later is a wiring change, not a rewrite.
"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.llm.provider import get_provider
from app.models.document import Document, DocumentPage
from app.models.manifest import Manifest
from app.models.processing_job import ProcessingJob
from app.models.redaction_candidate import RedactionCandidate
from app.models.usage_record import UsageRecord
from app.pipeline.detect import detect_page
from app.pipeline.detect_llm import detect_page_contextual
from app.pipeline.extract import extract_pdf
from app.pipeline.merge import MergeInput, group_recurrence, merge_overlapping
from app.services.audit_service import write_audit_event
from app.storage import get_store


async def _record_usage(session: AsyncSession, org_id: str, metric: str, quantity: int, doc_id: str, job_id: str) -> None:
    now = datetime.now(UTC)
    session.add(
        UsageRecord(
            id=new_id("use"), org_id=org_id, metric=metric, quantity=quantity,
            doc_id=doc_id, job_id=job_id, occurred_at=now, billing_period=now.strftime("%Y-%m"),
        )
    )


async def _merge_and_group(session: AsyncSession, org_id: str, all_candidates: list[RedactionCandidate]) -> None:
    """specs/05-redaction-pipeline.md Stage 5: dedupe overlapping candidates (deterministic
    + LLM may both flag the same span) and group cross-page recurrences. Mutates/deletes
    candidates in `session` directly; `all_candidates` must already be flushed (have ids)."""
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


async def process_document(session: AsyncSession, org_id: str, doc_id: str, actor_id: str) -> Manifest:
    """`session` must be org-scoped (app.org_id = org_id). Raises on failure — caller is
    responsible for marking the document `error` and writing the failure audit event
    (see app/routers/documents.py), since only it knows the original exception context."""
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

    for page in pages:
        preview_key = f"previews/{doc_id}/{page.page_no}.png"
        store.put(org_id, preview_key, page.preview_png)
        session.add(
            DocumentPage(
                id=new_id("pg"), doc_id=doc_id, org_id=org_id, page_no=page.page_no,
                s3_key_preview=preview_key, width=page.width, height=page.height,
                rotation=page.rotation, has_text_layer=page.has_text_layer,
                ocr_confidence=None,  # Phase 1: born-digital only, no OCR path yet
            )
        )

    document.page_count = len(pages)
    document.ocr_used = False
    extract_job.status = "succeeded"
    extract_job.ended_at = datetime.now(UTC)
    extract_job.metrics = {"pages": len(pages)}
    await _record_usage(session, org_id, "pages_processed", len(pages), doc_id, extract_job.id)
    await session.flush()

    document.status = "detecting"
    detect_job = ProcessingJob(id=new_id("job"), org_id=org_id, doc_id=doc_id, type="detect", status="running", started_at=datetime.now(UTC), attempt=1)
    session.add(detect_job)
    await session.flush()

    provider = get_provider()
    all_candidates: list[RedactionCandidate] = []
    total_hallucinated = 0
    total_llm_input_tokens = 0
    total_llm_output_tokens = 0
    llm_pages_used = 0

    for page in pages:
        deterministic = await detect_page(session, org_id, doc_id, page)
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
    if llm_pages_used:
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
    await session.flush()
    await session.refresh(manifest)
    return manifest
