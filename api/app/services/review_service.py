"""specs/03-data-model.md state machine: `redaction_candidates.state = approved` requires
`exemption_code_id` NOT NULL (enforced by a DB CHECK — this service just gives a clean 4xx
instead of letting the constraint violation surface as a raw 500)."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, NotFoundError
from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.models.document import Document
from app.models.manifest import Manifest
from app.models.organization import Organization
from app.models.redaction_candidate import RedactionCandidate
from app.models.review_action import ReviewAction
from app.services.audit_service import write_audit_event
from app.services.exemption_service import require_exemption_code_in_org


async def get_manifest_by_doc(session: AsyncSession, doc_id: str) -> Manifest:
    result = await session.execute(select(Manifest).where(Manifest.doc_id == doc_id))
    manifest = result.scalars().first()
    if manifest is None:
        raise NotFoundError("Manifest not found")
    return manifest


async def patch_candidate(
    session: AsyncSession,
    org_id: str,
    candidate_id: str,
    user_id: str,
    *,
    state: str | None,
    exemption_code_id: str | None,
    bbox: dict | None,
    ai_justification: str | None,
    note: str | None,
    if_match_version: int | None,
) -> RedactionCandidate:
    candidate = await session.get(RedactionCandidate, candidate_id)
    if candidate is None:
        raise NotFoundError("Candidate not found")

    manifest = await get_manifest_by_doc(session, candidate.doc_id)
    if if_match_version is not None and if_match_version != manifest.version:
        raise ApiError(409, "Conflict", "Manifest has changed since If-Match version (concurrent edit)")

    before = {"state": candidate.state, "exemption_code_id": candidate.exemption_code_id, "bbox": candidate.bbox}

    if exemption_code_id is not None:
        await require_exemption_code_in_org(session, exemption_code_id)
        candidate.exemption_code_id = exemption_code_id
    if bbox is not None:
        candidate.bbox = bbox
    if ai_justification is not None:
        # specs/10-build-plan.md Phase 2: "AI justifications editable in review panel" —
        # a reviewer's edit overwrites the model's own text; the original is only
        # recoverable via review_actions.payload.before, same as any other field edit.
        candidate.ai_justification = ai_justification
    if state is not None:
        # US-8: "approve button disabled until code selected" — API-enforced too, not just
        # UI. The DB CHECK constraint would also catch this, but a clean 422 here beats a
        # raw constraint-violation 500 reaching the client.
        if state == "approved" and candidate.exemption_code_id is None:
            raise ApiError(422, "Unprocessable Entity", "Cannot approve a candidate without an exemption code")
        candidate.state = state

    action = "modify" if bbox is not None else (state or "modify")
    session.add(
        ReviewAction(
            id=new_id("ract"), org_id=org_id, doc_id=candidate.doc_id, candidate_id=candidate.id,
            user_id=user_id, action=action if action in ("approve", "reject", "modify") else "modify",
            payload={"before": before, "note": note}, note=note,
        )
    )
    manifest.version += 1
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action=f"candidate.{'approved' if state == 'approved' else 'rejected' if state == 'rejected' else 'modified'}",
        # object_type/object_id = document, not the candidate, so GET /documents/{id}/events
        # (the document timeline view) can find every candidate-level event for a doc with
        # a single query — the candidate id still travels in metadata.
        object_type="document", object_id=candidate.doc_id, metadata={"candidate_id": candidate.id},
    )
    await session.flush()
    await session.refresh(candidate)
    return candidate


async def create_manual_candidate(
    session: AsyncSession,
    org_id: str,
    doc_id: str,
    user_id: str,
    *,
    page_no: int,
    bbox: dict,
    exemption_code_id: str,
    text: str,
    note: str | None,
) -> RedactionCandidate:
    await require_exemption_code_in_org(session, exemption_code_id)
    cipher = get_cipher()
    candidate = RedactionCandidate(
        id=new_id("cand"), org_id=org_id, doc_id=doc_id, page_no=page_no, bbox=bbox,
        display_text_encrypted=cipher.encrypt(org_id, text), origin="manual",
        exemption_code_id=exemption_code_id, confidence="n/a-manual", state="approved",
        detector_versions={},
    )
    session.add(candidate)
    session.add(
        ReviewAction(
            id=new_id("ract"), org_id=org_id, doc_id=doc_id, candidate_id=candidate.id,
            user_id=user_id, action="create", payload={"note": note}, note=note,
        )
    )
    manifest = await get_manifest_by_doc(session, doc_id)
    manifest.version += 1
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="candidate.created", object_type="document", object_id=doc_id,
        metadata={"candidate_id": candidate.id},
    )
    await session.flush()
    await session.refresh(candidate)
    return candidate


async def bulk_update_candidates(
    session: AsyncSession,
    org_id: str,
    doc_id: str,
    user_id: str,
    *,
    action: str,
    candidate_ids: list[str] | None = None,
    recurrence_group_id: str | None = None,
    confidence: str | None = None,
    exemption_code_id: str | None = None,
) -> list[RedactionCandidate]:
    """specs/04-api-spec.md POST /documents/{id}/candidates:bulk. Covers both US-6
    ("accept all high-confidence") via `confidence` and the review workspace's "apply to
    all similar" (right-click on a recurrence group) via `recurrence_group_id` — exactly
    one of `candidate_ids` / `recurrence_group_id` / `confidence` must be given."""
    if action not in ("approve", "reject"):
        raise ApiError(422, "Unprocessable Entity", "bulk action must be 'approve' or 'reject'")
    if action == "approve" and not exemption_code_id:
        raise ApiError(422, "Unprocessable Entity", "exemption_code_id is required to bulk-approve")
    if exemption_code_id:
        await require_exemption_code_in_org(session, exemption_code_id)

    selectors = [candidate_ids, recurrence_group_id, confidence]
    if sum(s is not None for s in selectors) != 1:
        raise ApiError(422, "Unprocessable Entity", "exactly one of candidate_ids/recurrence_group_id/confidence is required")

    query = select(RedactionCandidate).where(RedactionCandidate.doc_id == doc_id)
    if candidate_ids is not None:
        query = query.where(RedactionCandidate.id.in_(candidate_ids))
    elif recurrence_group_id is not None:
        query = query.where(RedactionCandidate.recurrence_group_id == recurrence_group_id)
    else:
        query = query.where(RedactionCandidate.confidence == confidence)

    result = await session.execute(query)
    candidates = result.scalars().all()

    manifest = await get_manifest_by_doc(session, doc_id)
    updated = []
    for candidate in candidates:
        before = {"state": candidate.state, "exemption_code_id": candidate.exemption_code_id}
        if action == "approve":
            candidate.exemption_code_id = exemption_code_id
        candidate.state = "approved" if action == "approve" else "rejected"
        session.add(
            ReviewAction(
                id=new_id("ract"), org_id=org_id, doc_id=doc_id, candidate_id=candidate.id,
                user_id=user_id, action="bulk_approve" if action == "approve" else "reject",
                payload={"before": before}, note=None,
            )
        )
        updated.append(candidate)

    if updated:
        manifest.version += 1
        await write_audit_event(
            session, org_id=org_id, actor_type="user", actor_id=user_id,
            action="candidate.approved" if action == "approve" else "candidate.rejected",
            object_type="document", object_id=doc_id,
            metadata={"bulk_count": len(updated), "selector": "recurrence_group" if recurrence_group_id else ("confidence" if confidence else "ids")},
        )
        await session.flush()
    return updated


async def complete_review(session: AsyncSession, org_id: str, doc_id: str, user_id: str) -> Document:
    """specs/04-api-spec.md POST /documents/{id}/review:complete — validates the
    completeness checklist (specs/03-data-model.md: zero unresolved low-confidence
    `suggested` candidates) before advancing document status.

    specs/03-data-model.md state machine: if the org has `dual_approval_required`, this
    lands on `awaiting_approval` (a supervisor/admin must call review:approve before
    export is possible) instead of going straight to `review_complete`. export_service.py
    only accepts documents in `review_complete`, so `awaiting_approval` is a hard,
    API-enforced block on export, not just a UI hint — see specs/10-build-plan.md Phase 3
    AC: "dual-approval org cannot export without supervisor action (API-enforced)".
    """
    document = await session.get(Document, doc_id)
    if document is None:
        raise NotFoundError("Document not found")

    result = await session.execute(
        select(RedactionCandidate).where(
            RedactionCandidate.doc_id == doc_id,
            RedactionCandidate.state == "suggested",
            RedactionCandidate.confidence == "low",
        )
    )
    unresolved = result.scalars().all()
    if unresolved:
        raise ApiError(
            422, "Unprocessable Entity",
            f"{len(unresolved)} low-confidence candidate(s) still unresolved — review them before completing.",
        )

    org = await session.get(Organization, org_id)
    assert org is not None
    dual_approval = bool(org.settings.get("dual_approval_required"))

    document.status = "awaiting_approval" if dual_approval else "review_complete"
    session.add(
        ReviewAction(
            id=new_id("ract"), org_id=org_id, doc_id=doc_id, candidate_id=None,
            user_id=user_id, action="complete_review", payload=None, note=None,
        )
    )
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="review.completed", object_type="document", object_id=doc_id,
        metadata={"dual_approval_required": dual_approval},
    )
    await session.flush()
    await session.refresh(document)
    return document


async def approve_document(session: AsyncSession, org_id: str, doc_id: str, user_id: str, note: str | None) -> Document:
    """specs/04-api-spec.md POST /documents/{id}/review:approve — supervisor/admin
    sign-off for dual-approval orgs. Only valid from `awaiting_approval`."""
    document = await session.get(Document, doc_id)
    if document is None:
        raise NotFoundError("Document not found")
    if document.status != "awaiting_approval":
        raise ApiError(422, "Unprocessable Entity", f"Document is not awaiting approval (status: {document.status})")

    document.status = "review_complete"
    session.add(
        ReviewAction(
            id=new_id("ract"), org_id=org_id, doc_id=doc_id, candidate_id=None,
            user_id=user_id, action="approve_doc", payload=None, note=note,
        )
    )
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="review.approved", object_type="document", object_id=doc_id, metadata={},
    )
    await session.flush()
    await session.refresh(document)
    return document


async def return_document(session: AsyncSession, org_id: str, doc_id: str, user_id: str, note: str | None) -> Document:
    """specs/04-api-spec.md POST /documents/{id}/review:return — supervisor sends a
    dual-approval document back for more work instead of approving it."""
    document = await session.get(Document, doc_id)
    if document is None:
        raise NotFoundError("Document not found")
    if document.status != "awaiting_approval":
        raise ApiError(422, "Unprocessable Entity", f"Document is not awaiting approval (status: {document.status})")

    document.status = "in_review"
    session.add(
        ReviewAction(
            id=new_id("ract"), org_id=org_id, doc_id=doc_id, candidate_id=None,
            user_id=user_id, action="return_doc", payload=None, note=note,
        )
    )
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="review.returned", object_type="document", object_id=doc_id, metadata={"note": note},
    )
    await session.flush()
    await session.refresh(document)
    return document


async def escalate_candidate(
    session: AsyncSession, org_id: str, candidate_id: str, user_id: str, note: str | None
) -> RedactionCandidate:
    """specs/01-product-spec.md US-10 / specs/07-ui-spec.md screen 3: "[Approve] [Reject]
    [Escalate]" — a third action independent of approve/reject; `state` is untouched."""
    candidate = await session.get(RedactionCandidate, candidate_id)
    if candidate is None:
        raise NotFoundError("Candidate not found")

    candidate.escalated_at = datetime.now(UTC)
    candidate.escalated_by = user_id
    candidate.escalated_note = note
    session.add(
        ReviewAction(
            id=new_id("ract"), org_id=org_id, doc_id=candidate.doc_id, candidate_id=candidate.id,
            user_id=user_id, action="escalate", payload=None, note=note,
        )
    )
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="candidate.escalated", object_type="document", object_id=candidate.doc_id,
        metadata={"candidate_id": candidate.id},
    )
    await session.flush()
    await session.refresh(candidate)
    return candidate


async def resolve_escalation(
    session: AsyncSession, org_id: str, candidate_id: str, user_id: str, note: str | None
) -> RedactionCandidate:
    candidate = await session.get(RedactionCandidate, candidate_id)
    if candidate is None:
        raise NotFoundError("Candidate not found")
    if candidate.escalated_at is None:
        raise ApiError(422, "Unprocessable Entity", "Candidate is not currently escalated")

    candidate.escalated_at = None
    candidate.escalated_by = None
    candidate.escalated_note = None
    session.add(
        ReviewAction(
            id=new_id("ract"), org_id=org_id, doc_id=candidate.doc_id, candidate_id=candidate.id,
            user_id=user_id, action="resolve_escalation", payload=None, note=note,
        )
    )
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="candidate.escalation_resolved", object_type="document", object_id=candidate.doc_id,
        metadata={"candidate_id": candidate.id},
    )
    await session.flush()
    await session.refresh(candidate)
    return candidate
