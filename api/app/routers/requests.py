from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_membership, get_org_db, require_role
from app.models.membership import Membership
from app.models.request import RecordsRequest
from app.schemas.legal_hold import LegalHoldRequest
from app.schemas.request import RequestCreate, RequestOut, RequestPatch
from app.services.legal_hold_service import clear_request_legal_hold, set_request_legal_hold
from app.services.request_service import create_request, get_request, list_requests, patch_request

router = APIRouter(tags=["requests"])


@router.post("/requests", response_model=RequestOut, status_code=201)
async def create_request_route(
    payload: RequestCreate,
    membership: Membership = Depends(get_membership),
    db: AsyncSession = Depends(get_org_db),
) -> RecordsRequest:
    return await create_request(db, membership.org_id, membership.user_id, payload)


@router.get("/requests", response_model=list[RequestOut])
async def list_requests_route(db: AsyncSession = Depends(get_org_db)) -> list[RecordsRequest]:
    return await list_requests(db)


@router.get("/requests/{request_id}", response_model=RequestOut)
async def get_request_route(request_id: str, db: AsyncSession = Depends(get_org_db)) -> RecordsRequest:
    return await get_request(db, request_id)


@router.patch("/requests/{request_id}", response_model=RequestOut)
async def patch_request_route(
    request_id: str,
    payload: RequestPatch,
    membership: Membership = Depends(get_membership),
    db: AsyncSession = Depends(get_org_db),
) -> RecordsRequest:
    return await patch_request(db, membership.org_id, membership.user_id, request_id, payload)


@router.post("/requests/{request_id}/legal-hold", response_model=RequestOut)
async def set_request_legal_hold_route(
    request_id: str,
    payload: LegalHoldRequest,
    membership: Membership = Depends(require_role("agency_admin", "supervisor")),
    db: AsyncSession = Depends(get_org_db),
) -> RecordsRequest:
    return await set_request_legal_hold(db, membership.org_id, membership.user_id, request_id, payload.note)


@router.delete("/requests/{request_id}/legal-hold", response_model=RequestOut)
async def clear_request_legal_hold_route(
    request_id: str,
    payload: LegalHoldRequest,
    membership: Membership = Depends(require_role("agency_admin", "supervisor")),
    db: AsyncSession = Depends(get_org_db),
) -> RecordsRequest:
    return await clear_request_legal_hold(db, membership.org_id, membership.user_id, request_id, payload.note)
