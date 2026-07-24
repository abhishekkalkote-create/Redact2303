"""specs/04-api-spec.md POST /documents/{id}/search-redact. `request` scope (across every
document in a Request) is deferred to Phase 3 — Requests grouping/batch work hasn't landed
yet; only `page`/`document` scope is implemented here.
"""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, NotFoundError
from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.models.document import Document
from app.models.redaction_candidate import RedactionCandidate
from app.pipeline.extract import extract_pdf, span_to_bbox
from app.services.audit_service import write_audit_event
from app.services.review_service import get_manifest_by_doc
from app.storage import get_store

VALID_SCOPES = ("page", "document")


async def search_and_redact(
    session: AsyncSession,
    org_id: str,
    doc_id: str,
    user_id: str,
    *,
    query: str,
    is_pattern: bool,
    scope: str,
    page_no: int | None,
    exemption_code_id: str,
) -> list[RedactionCandidate]:
    if scope not in VALID_SCOPES:
        raise ApiError(422, "Unprocessable Entity", f"scope must be one of {VALID_SCOPES} (request scope is Phase 3)")
    if scope == "page" and page_no is None:
        raise ApiError(422, "Unprocessable Entity", "page_no is required when scope=page")

    document = await session.get(Document, doc_id)
    if document is None:
        raise NotFoundError("Document not found")
    assert document.s3_key_original is not None

    original_bytes = get_store().get(org_id, document.s3_key_original)
    pages = extract_pdf(original_bytes)
    if scope == "page":
        pages = [p for p in pages if p.page_no == page_no]

    pattern = re.compile(query) if is_pattern else re.compile(re.escape(query))
    cipher = get_cipher()
    created: list[RedactionCandidate] = []

    for page in pages:
        for match in pattern.finditer(page.full_text):
            bbox = span_to_bbox(page.word_spans, match.start(), match.end())
            if bbox is None:
                continue
            candidate = RedactionCandidate(
                id=new_id("cand"), org_id=org_id, doc_id=doc_id, page_no=page.page_no, bbox=bbox,
                text_span={"start": match.start(), "end": match.end()},
                display_text_encrypted=cipher.encrypt(org_id, match.group(0)),
                origin="search_apply", exemption_code_id=exemption_code_id,
                confidence="n/a-manual", state="approved", detector_versions={},
            )
            session.add(candidate)
            created.append(candidate)

    if created:
        manifest = await get_manifest_by_doc(session, doc_id)
        manifest.version += 1
        await write_audit_event(
            session, org_id=org_id, actor_type="user", actor_id=user_id,
            action="candidate.created", object_type="document", object_id=doc_id,
            metadata={"scope": scope, "match_count": len(created), "search_apply": True},
        )
        await session.flush()
        for c in created:
            await session.refresh(c)
    return created
