from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
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
