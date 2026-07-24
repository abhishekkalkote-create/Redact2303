from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_membership, get_org_db
from app.models.membership import Membership
from app.schemas.export import CertificateVerifyResponse, ExportOut, ExportRequest
from app.services.export_service import create_export, verify_certificate_by_id

router = APIRouter(tags=["exports"])


@router.post("/documents/{doc_id}/exports", response_model=list[ExportOut], status_code=201)
async def export_document(
    doc_id: str,
    payload: ExportRequest,
    membership: Membership = Depends(get_membership),
    db: AsyncSession = Depends(get_org_db),
) -> list[ExportOut]:
    artifacts = await create_export(db, membership.org_id, doc_id, membership.user_id, tuple(payload.types))
    return [ExportOut.model_validate(a) for a in artifacts]


@router.get("/certificates/{certificate_id}/verify", response_model=CertificateVerifyResponse)
async def verify_certificate_route(certificate_id: str) -> CertificateVerifyResponse:
    """Deliberately public — no auth dependency. See migration 0004 for the RLS policy
    that makes this safe (declare-the-exact-id lookup, not a listing)."""
    result = await verify_certificate_by_id(certificate_id)
    return CertificateVerifyResponse(**result)
