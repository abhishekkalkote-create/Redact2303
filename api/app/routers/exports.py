from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_membership, get_org_db
from app.core.errors import NotFoundError
from app.models.export_artifact import ExportArtifact
from app.models.membership import Membership
from app.schemas.export import CertificateVerifyResponse, ExportOut, ExportRequest
from app.services.export_service import create_export, verify_certificate_by_id
from app.storage import get_store

router = APIRouter(tags=["exports"])

_CONTENT_TYPES = {
    "clean_pdf": "application/pdf",
    "annotated_pdf": "application/pdf",
    "certificate_pdf": "application/pdf",
    "exemption_log_csv": "text/csv",
    "exemption_log_pdf": "application/pdf",
    "exemption_log_json": "application/json",
}


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


@router.get("/exports/{export_id}/download")
async def download_export(export_id: str, db: AsyncSession = Depends(get_org_db)) -> Response:
    """specs/04-api-spec.md: "signed URL" in the real S3-backed design; served directly
    here for the same reason as page previews (app/storage/local.py) — still auth-gated
    and org-scoped via get_org_db, not public like certificate verification."""
    artifact = await db.get(ExportArtifact, export_id)
    if artifact is None:
        raise NotFoundError("Export not found")
    content = get_store().get(artifact.org_id, artifact.s3_key)
    content_type = _CONTENT_TYPES.get(artifact.type, "application/octet-stream")
    return Response(content=content, media_type=content_type)
