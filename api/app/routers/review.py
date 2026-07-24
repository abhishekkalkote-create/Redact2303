from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_membership, get_org_db
from app.crypto.envelope import get_cipher
from app.models.membership import Membership
from app.models.redaction_candidate import RedactionCandidate
from app.schemas.document import (
    BBox,
    CandidateCreate,
    CandidateOut,
    CandidatePatch,
    DocumentOut,
    SearchRedactRequest,
    SearchRedactResponse,
)
from app.services.review_service import complete_review, create_manual_candidate, patch_candidate
from app.services.search_service import search_and_redact

router = APIRouter(tags=["review"])


def _to_out(candidate: RedactionCandidate) -> CandidateOut:
    cipher = get_cipher()
    return CandidateOut(
        id=candidate.id, page_no=candidate.page_no, bbox=BBox(**candidate.bbox),
        display_text=cipher.decrypt(candidate.org_id, candidate.display_text_encrypted),
        origin=candidate.origin, source_rule_key=candidate.source_rule_key,
        exemption_code_id=candidate.exemption_code_id, exemption_code=None,
        ai_justification=candidate.ai_justification, confidence=candidate.confidence,
        state=candidate.state,
    )


@router.post("/documents/{doc_id}/candidates", response_model=CandidateOut, status_code=201)
async def create_candidate(
    doc_id: str,
    payload: CandidateCreate,
    membership: Membership = Depends(get_membership),
    db: AsyncSession = Depends(get_org_db),
) -> CandidateOut:
    candidate = await create_manual_candidate(
        db, membership.org_id, doc_id, membership.user_id,
        page_no=payload.page_no, bbox=payload.bbox.model_dump(),
        exemption_code_id=payload.exemption_code_id, text="[manual redaction]", note=payload.note,
    )
    return _to_out(candidate)


@router.patch("/candidates/{candidate_id}", response_model=CandidateOut)
async def patch_candidate_route(
    candidate_id: str,
    payload: CandidatePatch,
    membership: Membership = Depends(get_membership),
    db: AsyncSession = Depends(get_org_db),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> CandidateOut:
    candidate = await patch_candidate(
        db, membership.org_id, candidate_id, membership.user_id,
        state=payload.state, exemption_code_id=payload.exemption_code_id,
        bbox=payload.bbox.model_dump() if payload.bbox else None,
        ai_justification=payload.ai_justification, note=payload.note,
        if_match_version=int(if_match) if if_match else None,
    )
    return _to_out(candidate)


@router.post("/documents/{doc_id}/review:complete", response_model=DocumentOut)
async def complete_review_route(
    doc_id: str,
    membership: Membership = Depends(get_membership),
    db: AsyncSession = Depends(get_org_db),
):
    return await complete_review(db, membership.org_id, doc_id, membership.user_id)


@router.post("/documents/{doc_id}/search-redact", response_model=SearchRedactResponse)
async def search_redact_route(
    doc_id: str,
    payload: SearchRedactRequest,
    membership: Membership = Depends(get_membership),
    db: AsyncSession = Depends(get_org_db),
) -> SearchRedactResponse:
    created = await search_and_redact(
        db, membership.org_id, doc_id, membership.user_id,
        query=payload.query, is_pattern=payload.is_pattern, scope=payload.scope,
        page_no=payload.page_no, exemption_code_id=payload.exemption_code_id,
    )
    return SearchRedactResponse(created=[_to_out(c) for c in created])
