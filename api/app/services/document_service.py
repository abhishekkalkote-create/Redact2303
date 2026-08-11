from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.crypto.envelope import get_cipher
from app.models.document import Document
from app.models.exemption_code import ExemptionCode
from app.models.manifest import Manifest
from app.models.redaction_candidate import RedactionCandidate


async def list_documents(
    session: AsyncSession,
    *,
    status: str | None = None,
    request_id: str | None = None,
    assignee_id: str | None = None,
    escalated: bool | None = None,
    sort: str | None = None,
) -> list[Document]:
    """specs/01-product-spec.md US-16: "queue dashboards" (assignee filter = "my
    queue"/"team queue"); US-10's supervisor escalation queue (`escalated=true`); and
    specs/07-ui-spec.md screen 2's "My queue ... sorted low-confidence-first option"
    (`sort="low_confidence_first"`), which prioritizes documents with the most
    unresolved low-confidence candidates — the same "unresolved" definition
    review_service.complete_review gates on."""
    query = select(Document)
    if status:
        query = query.where(Document.status == status)
    if request_id:
        query = query.where(Document.request_id == request_id)
    if assignee_id:
        query = query.where(Document.assignee_id == assignee_id)
    if escalated:
        query = query.where(
            exists().where(RedactionCandidate.doc_id == Document.id, RedactionCandidate.escalated_at.is_not(None))
        )

    if sort == "low_confidence_first":
        low_confidence_count = (
            select(func.count(RedactionCandidate.id))
            .where(
                RedactionCandidate.doc_id == Document.id,
                RedactionCandidate.state == "suggested",
                RedactionCandidate.confidence == "low",
            )
            .correlate(Document)
            .scalar_subquery()
        )
        query = query.order_by(low_confidence_count.desc(), Document.created_at.desc())
    else:
        query = query.order_by(Document.created_at.desc())

    result = await session.execute(query)
    return list(result.scalars().all())


async def get_manifest_data(session: AsyncSession, doc_id: str) -> dict:
    """Shared by app/routers/documents.py's GET /documents/{id}/manifest and
    app/services/offboarding_service.py's export package — same decrypt-and-shape logic
    either way, so the two never drift. Returns a plain dict (schema-wrapping is the
    router's job, matching this codebase's other services) rather than a Pydantic model
    directly."""
    manifest = (await session.execute(select(Manifest).where(Manifest.doc_id == doc_id))).scalars().first()
    if manifest is None:
        raise NotFoundError("Manifest not found (document may still be processing)")

    result = await session.execute(
        select(RedactionCandidate, ExemptionCode.code)
        .outerjoin(ExemptionCode, RedactionCandidate.exemption_code_id == ExemptionCode.id)
        .where(RedactionCandidate.doc_id == doc_id)
        .order_by(RedactionCandidate.page_no, RedactionCandidate.id)
    )
    cipher = get_cipher()
    candidates = [
        {
            "id": c.id, "page_no": c.page_no, "bbox": c.bbox,
            "display_text": cipher.decrypt(manifest.org_id, c.display_text_encrypted),
            "origin": c.origin, "source_rule_key": c.source_rule_key,
            "exemption_code_id": c.exemption_code_id, "exemption_code": code,
            "ai_justification": c.ai_justification, "confidence": c.confidence, "state": c.state,
            "recurrence_group_id": c.recurrence_group_id,
            "escalated_at": c.escalated_at, "escalated_note": c.escalated_note,
        }
        for c, code in result.all()
    ]
    return {
        "doc_id": doc_id, "version": manifest.version, "schema_version": manifest.schema_version,
        "completeness": manifest.completeness, "candidates": candidates,
    }
