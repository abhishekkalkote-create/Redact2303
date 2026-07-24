from fastapi import APIRouter, Depends, Form, Query, Response, UploadFile
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
from app.pipeline.email_intake import (
    is_eml_mime,
    is_msg_container_mime,
    parse_eml,
    parse_msg,
    render_email_body_to_pdf,
)
from app.pipeline.intake import (
    IntakeError,
    content_sha256,
    expand_zip,
    is_zip_mime,
    sniff_mime,
    validate_and_scan,
)
from app.pipeline.run import process_document
from app.schemas.document import (
    BatchRejection,
    BatchUploadResult,
    BBox,
    CandidateOut,
    DocumentAssignPatch,
    DocumentOut,
    ManifestOut,
    PageOut,
)
from app.schemas.request import RequestCreate, RequestOut
from app.services.audit_service import write_audit_event
from app.services.document_service import list_documents as list_documents_query
from app.services.request_service import create_request
from app.storage import get_store

router = APIRouter(tags=["documents"])


async def _create_and_process_document(
    db: AsyncSession,
    membership: Membership,
    *,
    filename: str,
    mime_type: str,
    data: bytes,
    request_id: str | None,
    source: str,
) -> Document:
    doc_id = new_id("doc")
    store = get_store()
    original_key = f"originals/{doc_id}"
    store.put(membership.org_id, original_key, data)

    document = Document(
        id=doc_id, org_id=membership.org_id, filename=filename,
        mime_type=mime_type, source=source, status="uploaded", request_id=request_id,
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


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    membership: Membership = Depends(get_membership),
    db: AsyncSession = Depends(get_org_db),
    status: str | None = Query(default=None),
    request_id: str | None = Query(default=None),
    assignee: str | None = Query(default=None, description='"me" or a user id'),
    escalated: bool | None = Query(default=None, description="only documents with an active candidate escalation"),
    sort: str | None = Query(default=None, description='"low_confidence_first" or omit for newest-first'),
) -> list[Document]:
    """specs/01-product-spec.md US-16: "queue dashboards" — `assignee=me` is the "my
    queue" filter; a supervisor omits it (or passes another user's id) for "team queue".
    `escalated=true` is US-10's supervisor escalation queue. `sort=low_confidence_first`
    is the Dashboard's "My queue ... sorted low-confidence-first option" (specs/07-ui-spec.md
    screen 2)."""
    assignee_id = membership.user_id if assignee == "me" else assignee
    return await list_documents_query(
        db, status=status, request_id=request_id, assignee_id=assignee_id, escalated=escalated, sort=sort,
    )


@router.post("/documents", response_model=BatchUploadResult, status_code=201)
async def upload_document(
    file: UploadFile,
    request_id: str | None = Form(default=None),
    membership: Membership = Depends(get_membership),
    db: AsyncSession = Depends(get_org_db),
) -> BatchUploadResult:
    """specs/04-api-spec.md upload finalize: "creates document(s)". A ZIP is expanded
    into child documents (specs/05-redaction-pipeline.md Stage 1: "flatten one level;
    nested zips rejected") — bad entries are collected in `rejected` rather than failing
    the whole batch; a plain PDF still raises IntakeError (422) on validation failure,
    same as before ZIP support existed. An .eml/.msg becomes a new Request with the
    rendered body plus every attachment as child documents (Stage 1: "EML/MSG: parse
    headers/body/attachments into a Request with child documents")."""
    data = await file.read()
    outer_mime = sniff_mime(data)

    is_msg = is_msg_container_mime(outer_mime) and (file.filename or "").lower().endswith(".msg")
    if is_eml_mime(outer_mime) or is_msg:
        parsed = parse_msg(data) if is_msg else parse_eml(data)
        request = await create_request(
            db, membership.org_id, membership.user_id,
            RequestCreate(title=parsed.subject, reference_no=parsed.message_id),
        )

        body_pdf = render_email_body_to_pdf(parsed)
        documents = [
            await _create_and_process_document(
                db, membership, filename="email-body.pdf", mime_type=validate_and_scan(body_pdf),
                data=body_pdf, request_id=request.id, source="email",
            )
        ]
        rejected_pairs: list[tuple[str, str]] = []
        for filename, att_bytes in parsed.attachments:
            try:
                mime_type = validate_and_scan(att_bytes)
            except IntakeError as exc:
                rejected_pairs.append((filename, exc.detail or "validation failed"))
                continue
            documents.append(
                await _create_and_process_document(
                    db, membership, filename=filename, mime_type=mime_type, data=att_bytes,
                    request_id=request.id, source="email",
                )
            )
        return BatchUploadResult(
            documents=[DocumentOut.model_validate(d) for d in documents],
            rejected=[BatchRejection(filename=f, reason=r) for f, r in rejected_pairs],
            request=RequestOut.model_validate(request),
        )

    if is_zip_mime(outer_mime):
        entries, rejected_pairs = expand_zip(data)  # raises IntakeError on archive-level failure
        batch_documents: list[Document] = []
        for filename, member_bytes in entries:
            try:
                mime_type = validate_and_scan(member_bytes)
            except IntakeError as exc:
                rejected_pairs.append((filename, exc.detail or "validation failed"))
                continue
            document = await _create_and_process_document(
                db, membership, filename=filename, mime_type=mime_type, data=member_bytes,
                request_id=request_id, source="batch",
            )
            batch_documents.append(document)
        return BatchUploadResult(
            documents=[DocumentOut.model_validate(d) for d in batch_documents],
            rejected=[BatchRejection(filename=f, reason=r) for f, r in rejected_pairs],
        )

    mime_type = validate_and_scan(data)  # raises IntakeError (422) on failure
    document = await _create_and_process_document(
        db, membership, filename=file.filename or "upload.pdf", mime_type=mime_type,
        data=data, request_id=request_id, source="upload",
    )
    return BatchUploadResult(documents=[DocumentOut.model_validate(document)], rejected=[])


@router.get("/documents/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: str, db: AsyncSession = Depends(get_org_db)
) -> Document:
    document = await db.get(Document, doc_id)
    if document is None:
        raise NotFoundError("Document not found")
    return document


@router.patch("/documents/{doc_id}", response_model=DocumentOut)
async def patch_document(
    doc_id: str,
    payload: DocumentAssignPatch,
    membership: Membership = Depends(get_membership),
    db: AsyncSession = Depends(get_org_db),
) -> Document:
    """specs/04-api-spec.md PATCH /documents/{id} — assign, due_date, request_id."""
    document = await db.get(Document, doc_id)
    if document is None:
        raise NotFoundError("Document not found")
    updates = payload.model_dump(exclude_none=True)
    for key, value in updates.items():
        setattr(document, key, value)
    if updates:
        await write_audit_event(
            db, org_id=membership.org_id, actor_type="user", actor_id=membership.user_id,
            action="document.assigned", object_type="document", object_id=doc_id,
            metadata={"fields": list(updates)},
        )
    await db.flush()
    await db.refresh(document)
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
            escalated_at=c.escalated_at, escalated_note=c.escalated_note,
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
