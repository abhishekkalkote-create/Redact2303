"""specs/08-security-compliance.md § Data lifecycle: "Retention: org-configurable —
uploads/originals (default 90 days post-export)... Legal-hold flag per document/request
suspends deletion." "Deletion: soft delete -> scheduled S3 deletion + DB purge of
content columns; certificate of deletion available."

Export retention ("exports (default 7 years)") is deliberately NOT built here.
app/models/export_artifact.py is explicitly documented "Immutable — no UPDATE/DELETE
once written"; actively deleting export content on a schedule would need that
invariant revisited first (a soft-delete-friendly redesign, or accepting an S3-only
deletion that leaves a dangling DB reference) — a bigger design call than a retention
slice should make unilaterally. This only purges document originals/previews, which is
also the shorter, more privacy-sensitive horizon (90 days vs. 7 years).

"exported_at" isn't a stored column — derived from the earliest export_artifacts row
for the document. A document's status is terminal once "exported"
(app/pipeline/run.py's _NOT_REPROCESSABLE_STATUSES), so there's exactly one export
event to anchor the retention clock on.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import fitz
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.audit_event import AuditEvent
from app.models.document import Document, DocumentPage
from app.models.export_artifact import ExportArtifact
from app.models.organization import Organization
from app.models.request import RecordsRequest
from app.services.audit_service import write_audit_event
from app.storage import get_store


async def find_documents_eligible_for_purge(session: AsyncSession, org: Organization, now: datetime) -> list[str]:
    retention_days = org.settings.get("retention_days_uploads", 90)
    cutoff = now - timedelta(days=retention_days)

    exported_at = (
        select(func.min(ExportArtifact.created_at))
        .where(ExportArtifact.doc_id == Document.id)
        .correlate(Document)
        .scalar_subquery()
    )

    result = await session.execute(
        select(Document.id)
        .outerjoin(RecordsRequest, Document.request_id == RecordsRequest.id)
        .where(
            Document.org_id == org.id,
            Document.status == "exported",
            Document.deleted_at.is_(None),
            Document.legal_hold.is_(False),
            (RecordsRequest.id.is_(None)) | (RecordsRequest.legal_hold.is_(False)),
            exported_at <= cutoff,
        )
    )
    return [row[0] for row in result.all()]


async def purge_document_content(session: AsyncSession, org_id: str, doc_id: str, now: datetime) -> bool:
    """Deletes the S3 original + every page preview ("page previews follow originals")
    and nulls the DB's content-bearing columns. The document ROW survives, deleted_at
    marking it — same soft-delete shape as every other content purge in this codebase,
    never a hard DELETE of the row itself. Returns False (no-op) if the document turns
    out to be on legal hold.

    Security self-review finding (TOCTOU): callers (find_documents_eligible_for_purge /
    find_documents_eligible_for_offboarding_purge) check legal_hold once, up front, then
    hand over a list of doc_ids — a multi-document sweep can take long enough for a hold
    to be placed on a later document in that list after the eligibility query already
    ran. Re-checking here, immediately before destroying anything, closes that window."""
    document = await session.get(Document, doc_id)
    if document is None:
        raise NotFoundError("Document not found")
    if document.legal_hold:
        return False
    if document.request_id is not None:
        request = await session.get(RecordsRequest, document.request_id)
        if request is not None and request.legal_hold:
            return False

    store = get_store()
    sha256_at_purge = document.content_sha256
    if document.s3_key_original:
        store.delete(org_id, document.s3_key_original)

    pages_result = await session.execute(select(DocumentPage).where(DocumentPage.doc_id == doc_id))
    for page in pages_result.scalars().all():
        if page.s3_key_preview:
            store.delete(org_id, page.s3_key_preview)
        page.s3_key_preview = None

    document.s3_key_original = None
    document.content_sha256 = None
    document.deleted_at = now

    await write_audit_event(
        session, org_id=org_id, actor_type="system", actor_id="retention_sweep",
        action="document.retention_purged", object_type="document", object_id=doc_id,
        metadata={"purged_at": now.isoformat(), "sha256_at_purge": sha256_at_purge, "filename": document.filename},
    )
    await session.flush()
    return True


async def run_retention_sweep(session: AsyncSession, org: Organization, now: datetime) -> int:
    doc_ids = await find_documents_eligible_for_purge(session, org, now)
    purged_count = 0
    for doc_id in doc_ids:
        if await purge_document_content(session, org.id, doc_id, now):
            purged_count += 1
    return purged_count


@dataclass
class DeletionCertificateFacts:
    doc_id: str
    filename: str
    org_id: str
    purged_at: str
    sha256_at_purge: str | None


async def get_deletion_certificate_facts(session: AsyncSession, org_id: str, doc_id: str) -> DeletionCertificateFacts:
    """The certificate reads straight off the hash-chained, append-only audit_events row
    the purge itself wrote — a stronger source of truth than a separately stored PDF
    would be, and needs no new storage of its own."""
    result = await session.execute(
        select(AuditEvent)
        .where(AuditEvent.org_id == org_id, AuditEvent.object_id == doc_id, AuditEvent.action == "document.retention_purged")
        .order_by(AuditEvent.created_at.desc())
        .limit(1)
    )
    event = result.scalars().first()
    if event is None:
        raise NotFoundError("This document has not been through the retention sweep — no deletion certificate exists")
    metadata = event.metadata_
    return DeletionCertificateFacts(
        doc_id=doc_id, filename=metadata["filename"], org_id=org_id,
        purged_at=metadata["purged_at"], sha256_at_purge=metadata.get("sha256_at_purge"),
    )


def generate_deletion_certificate_pdf(facts: DeletionCertificateFacts) -> bytes:
    """Same fitz-primitives approach as app/pipeline/export.py's
    generate_certificate_pdf — generated on demand from the facts above, never stored,
    so there's nothing here that itself needs a retention policy."""
    doc = fitz.open()
    page = doc.new_page()
    lines = [
        "REDACTPROOF — CERTIFICATE OF DELETION",
        "",
        f"Document ID: {facts.doc_id}",
        f"Filename: {facts.filename}",
        f"Purged (UTC): {facts.purged_at}",
        f"SHA-256 at time of purge: {facts.sha256_at_purge or '(none recorded)'}",
        "",
        "This certificate attests that the original document content and page previews",
        "listed above were deleted from storage per the organization's retention policy",
        "(specs/08-security-compliance.md), following the applicable legal-hold check.",
    ]
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 18
    return doc.tobytes()
