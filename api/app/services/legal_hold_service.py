"""specs/08-security-compliance.md § Data lifecycle: "Legal-hold flag per
document/request suspends deletion." Toggling is deliberately its own action-style
endpoint (not folded into PATCH /documents/{id} or PATCH /requests/{id}) so it can carry
its own role gate — a compliance action, not routine reassignment — matching
app/routers/documents.py's process_document_route/review.py's other
document-wide, decision-affecting actions (require_role("agency_admin", "supervisor")).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.document import Document
from app.models.request import RecordsRequest
from app.services.audit_service import write_audit_event


async def set_document_legal_hold(session: AsyncSession, org_id: str, actor_id: str, doc_id: str, note: str | None) -> Document:
    document = await session.get(Document, doc_id)
    if document is None:
        raise NotFoundError("Document not found")
    document.legal_hold = True
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=actor_id,
        action="document.legal_hold_set", object_type="document", object_id=doc_id, metadata={"note": note},
    )
    await session.flush()
    await session.refresh(document)
    return document


async def clear_document_legal_hold(session: AsyncSession, org_id: str, actor_id: str, doc_id: str, note: str | None) -> Document:
    document = await session.get(Document, doc_id)
    if document is None:
        raise NotFoundError("Document not found")
    document.legal_hold = False
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=actor_id,
        action="document.legal_hold_cleared", object_type="document", object_id=doc_id, metadata={"note": note},
    )
    await session.flush()
    await session.refresh(document)
    return document


async def set_request_legal_hold(
    session: AsyncSession, org_id: str, actor_id: str, request_id: str, note: str | None
) -> RecordsRequest:
    request = await session.get(RecordsRequest, request_id)
    if request is None:
        raise NotFoundError("Request not found")
    request.legal_hold = True
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=actor_id,
        action="request.legal_hold_set", object_type="request", object_id=request_id, metadata={"note": note},
    )
    await session.flush()
    await session.refresh(request)
    return request


async def clear_request_legal_hold(
    session: AsyncSession, org_id: str, actor_id: str, request_id: str, note: str | None
) -> RecordsRequest:
    request = await session.get(RecordsRequest, request_id)
    if request is None:
        raise NotFoundError("Request not found")
    request.legal_hold = False
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=actor_id,
        action="request.legal_hold_cleared", object_type="request", object_id=request_id, metadata={"note": note},
    )
    await session.flush()
    await session.refresh(request)
    return request
