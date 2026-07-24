from fastapi import APIRouter, Depends, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_membership, get_org_db
from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.models.document import Document, DocumentPage
from app.models.exemption_code import ExemptionCode
from app.models.manifest import Manifest
from app.models.membership import Membership
from app.models.redaction_candidate import RedactionCandidate
from app.pipeline.intake import content_sha256, validate_and_scan
from app.pipeline.run import process_document
from app.schemas.document import BBox, CandidateOut, DocumentOut, ManifestOut, PageOut
from app.services.audit_service import write_audit_event
from app.storage import get_store

router = APIRouter(tags=["documents"])


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(db: AsyncSession = Depends(get_org_db)) -> list[Document]:
    result = await db.execute(select(Document).order_by(Document.created_at.desc()))
    return list(result.scalars().all())


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile,
    membership: Membership = Depends(get_membership),
    db: AsyncSession = Depends(get_org_db),
) -> Document:
    data = await file.read()
    mime_type = validate_and_scan(data)  # raises IntakeError (422) on failure

    doc_id = new_id("doc")
    store = get_store()
    original_key = f"originals/{doc_id}"
    store.put(membership.org_id, original_key, data)

    document = Document(
        id=doc_id, org_id=membership.org_id, filename=file.filename or "upload.pdf",
        mime_type=mime_type, source="upload", status="uploaded",
        uploaded_by=membership.user_id, s3_key_original=original_key,
        content_sha256=content_sha256(data),
    )
    db.add(document)
    await db.flush()
    await write_audit_event(
        db, org_id=membership.org_id, actor_type="user", actor_id=membership.user_id,
        action="document.uploaded", object_type="document", object_id=doc_id,
        metadata={"mime_type": mime_type, "size_bytes": len(data)},
    )
    await db.flush()

    try:
        await process_document(db, membership.org_id, doc_id, actor_id=membership.user_id)
    except Exception as exc:  # noqa: BLE001 — deliberately broad: any pipeline failure (
        # extraction, detection, storage) must land the document in `error` with an audit
        # trail rather than propagate as an unhandled 500 and leave it stuck mid-pipeline.
        document.status = "error"
        document.error = {"message": str(exc)}
        await write_audit_event(
            db, org_id=membership.org_id, actor_type="system", actor_id=membership.user_id,
            action="document.processing_failed", object_type="document", object_id=doc_id,
            metadata={"error": str(exc)},
        )
        await db.flush()

    await db.refresh(document)
    return document


@router.get("/documents/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: str, db: AsyncSession = Depends(get_org_db)
) -> Document:
    document = await db.get(Document, doc_id)
    if document is None:
        raise NotFoundError("Document not found")
    return document


@router.get("/documents/{doc_id}/manifest", response_model=ManifestOut)
async def get_manifest(doc_id: str, db: AsyncSession = Depends(get_org_db)) -> ManifestOut:
    manifest = (await db.execute(select(Manifest).where(Manifest.doc_id == doc_id))).scalars().first()
    if manifest is None:
        raise NotFoundError("Manifest not found (document may still be processing)")

    result = await db.execute(
        select(RedactionCandidate, ExemptionCode.code)
        .outerjoin(ExemptionCode, RedactionCandidate.exemption_code_id == ExemptionCode.id)
        .where(RedactionCandidate.doc_id == doc_id)
        .order_by(RedactionCandidate.page_no, RedactionCandidate.id)
    )
    cipher = get_cipher()
    candidates = [
        CandidateOut(
            id=c.id, page_no=c.page_no, bbox=BBox(**c.bbox),
            display_text=cipher.decrypt(manifest.org_id, c.display_text_encrypted),
            origin=c.origin, source_rule_key=c.source_rule_key,
            exemption_code_id=c.exemption_code_id, exemption_code=code,
            ai_justification=c.ai_justification, confidence=c.confidence, state=c.state,
            recurrence_group_id=c.recurrence_group_id,
        )
        for c, code in result.all()
    ]
    return ManifestOut(
        doc_id=doc_id, version=manifest.version, schema_version=manifest.schema_version,
        completeness=manifest.completeness, candidates=candidates,
    )


@router.get("/documents/{doc_id}/pages", response_model=list[PageOut])
async def list_pages(doc_id: str, db: AsyncSession = Depends(get_org_db)) -> list[DocumentPage]:
    result = await db.execute(
        select(DocumentPage).where(DocumentPage.doc_id == doc_id).order_by(DocumentPage.page_no)
    )
    return list(result.scalars().all())


@router.get("/documents/{doc_id}/pages/{page_no}/preview")
async def get_page_preview(doc_id: str, page_no: int, db: AsyncSession = Depends(get_org_db)) -> Response:
    """specs/04-api-spec.md: "short-lived signed URL for rendered page image" in the real
    S3-backed design; served directly here since there's no S3/CDN to sign a URL against
    yet (app/storage/local.py). Still auth-gated the same way — org-scoped, not public."""
    result = await db.execute(
        select(DocumentPage).where(DocumentPage.doc_id == doc_id, DocumentPage.page_no == page_no)
    )
    page = result.scalars().first()
    if page is None or page.s3_key_preview is None:
        raise NotFoundError("Page preview not found")

    png_bytes = get_store().get(page.org_id, page.s3_key_preview)
    return Response(content=png_bytes, media_type="image/png")
