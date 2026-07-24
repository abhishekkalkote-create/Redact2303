from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.models.request import RecordsRequest
from app.schemas.request import RequestCreate, RequestPatch
from app.services.audit_service import write_audit_event


async def create_request(session: AsyncSession, org_id: str, user_id: str, payload: RequestCreate) -> RecordsRequest:
    request = RecordsRequest(
        id=new_id("req"), org_id=org_id, title=payload.title, reference_no=payload.reference_no,
        due_date=payload.due_date, assignee_id=payload.assignee_id,
    )
    session.add(request)
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="request.created", object_type="request", object_id=request.id, metadata={},
    )
    await session.flush()
    await session.refresh(request)
    return request


async def list_requests(session: AsyncSession) -> list[RecordsRequest]:
    result = await session.execute(select(RecordsRequest).order_by(RecordsRequest.created_at.desc()))
    return list(result.scalars().all())


async def get_request(session: AsyncSession, request_id: str) -> RecordsRequest:
    request = await session.get(RecordsRequest, request_id)
    if request is None:
        raise NotFoundError("Request not found")
    return request


async def patch_request(session: AsyncSession, org_id: str, user_id: str, request_id: str, payload: RequestPatch) -> RecordsRequest:
    request = await get_request(session, request_id)
    updates = payload.model_dump(exclude_none=True)
    for key, value in updates.items():
        setattr(request, key, value)
    if updates:
        await write_audit_event(
            session, org_id=org_id, actor_type="user", actor_id=user_id,
            action="request.updated", object_type="request", object_id=request.id, metadata={"fields": list(updates)},
        )
    await session.flush()
    await session.refresh(request)
    return request
