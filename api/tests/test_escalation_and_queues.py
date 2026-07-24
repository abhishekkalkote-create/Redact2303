"""specs/01-product-spec.md US-10 (escalation queue), US-16 (queue dashboards, "sorted
low-confidence-first option", specs/07-ui-spec.md screen 2). Escalation is a candidate-
level flag independent of state (suggested/approved/rejected) — [Approve] [Reject]
[Escalate] are three separate actions per screen 3."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.ids import new_id
from app.models.document import Document
from app.models.manifest import Manifest
from app.models.redaction_candidate import RedactionCandidate
from app.services.document_service import list_documents
from app.services.review_service import (
    create_manual_candidate,
    escalate_candidate,
    resolve_escalation,
)
from tests.conftest import set_org


async def _seed_org_user(session: AsyncSession, org_id: str, user_id: str) -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'other', 'pilot', 'trialing', '{}')"
        ),
        {"id": org_id},
    )
    await session.execute(
        text(
            "INSERT INTO users (id, email, name, status) VALUES "
            "(:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )


async def _seed_document_with_manifest(session: AsyncSession, org_id: str, user_id: str, doc_id: str) -> None:
    session.add(
        Document(
            id=doc_id, org_id=org_id, filename="sample.pdf", mime_type="application/pdf",
            source="upload", status="ready_for_review", uploaded_by=user_id, content_sha256="deadbeef",
        )
    )
    session.add(Manifest(id=new_id("man"), org_id=org_id, doc_id=doc_id, version=1))


async def _seed_exemption_code(session: AsyncSession, org_id: str) -> str:
    code_id = new_id("exc")
    await session.execute(
        text(
            "INSERT INTO exemption_codes (id, org_id, code, label, status) VALUES "
            "(:id, :org_id, 'TEST-1', 'Test exemption', 'active')"
        ),
        {"id": code_id, "org_id": org_id},
    )
    return code_id


@pytest.mark.asyncio
async def test_escalate_and_resolve_candidate(db_session: AsyncSession) -> None:
    org_id, user_id, doc_id = "org_esc_1", "usr_esc_1", new_id("doc")
    async with db_session.begin():
        await _seed_org_user(db_session, org_id, user_id)
        await _seed_document_with_manifest(db_session, org_id, user_id, doc_id)
        exemption_code_id = await _seed_exemption_code(db_session, org_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        candidate = await create_manual_candidate(
            db_session, org_id, doc_id, user_id,
            page_no=1, bbox={"x": 0, "y": 0, "w": 10, "h": 10},
            exemption_code_id=exemption_code_id, text="secret", note=None,
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        escalated = await escalate_candidate(db_session, org_id, candidate.id, user_id, "looks off, please review")
        assert escalated.escalated_at is not None
        assert escalated.escalated_by == user_id
        assert escalated.escalated_note == "looks off, please review"
        assert escalated.state == "approved", "escalation must not touch candidate.state"

    async with db_session.begin():
        await set_org(db_session, org_id)
        result = await db_session.execute(
            text("SELECT action FROM audit_events WHERE object_type = 'document' AND object_id = :doc_id ORDER BY id"),
            {"doc_id": doc_id},
        )
        actions = [row[0] for row in result.all()]
        assert "candidate.escalated" in actions

    async with db_session.begin():
        await set_org(db_session, org_id)
        resolved = await resolve_escalation(db_session, org_id, candidate.id, user_id, "handled")
        assert resolved.escalated_at is None
        assert resolved.escalated_by is None
        assert resolved.escalated_note is None


@pytest.mark.asyncio
async def test_resolve_escalation_rejects_when_not_escalated(db_session: AsyncSession) -> None:
    org_id, user_id, doc_id = "org_esc_2", "usr_esc_2", new_id("doc")
    async with db_session.begin():
        await _seed_org_user(db_session, org_id, user_id)
        await _seed_document_with_manifest(db_session, org_id, user_id, doc_id)
        exemption_code_id = await _seed_exemption_code(db_session, org_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        candidate = await create_manual_candidate(
            db_session, org_id, doc_id, user_id,
            page_no=1, bbox={"x": 0, "y": 0, "w": 10, "h": 10},
            exemption_code_id=exemption_code_id, text="secret", note=None,
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        with pytest.raises(ApiError) as exc_info:
            await resolve_escalation(db_session, org_id, candidate.id, user_id, None)
        assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_list_documents_escalated_filter(db_session: AsyncSession) -> None:
    org_id, user_id = "org_esc_3", "usr_esc_3"
    doc_a, doc_b = new_id("doc"), new_id("doc")
    async with db_session.begin():
        await _seed_org_user(db_session, org_id, user_id)
        await _seed_document_with_manifest(db_session, org_id, user_id, doc_a)
        await _seed_document_with_manifest(db_session, org_id, user_id, doc_b)
        exemption_code_id = await _seed_exemption_code(db_session, org_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        candidate_a = await create_manual_candidate(
            db_session, org_id, doc_a, user_id,
            page_no=1, bbox={"x": 0, "y": 0, "w": 10, "h": 10},
            exemption_code_id=exemption_code_id, text="secret a", note=None,
        )
        await create_manual_candidate(
            db_session, org_id, doc_b, user_id,
            page_no=1, bbox={"x": 0, "y": 0, "w": 10, "h": 10},
            exemption_code_id=exemption_code_id, text="secret b", note=None,
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        await escalate_candidate(db_session, org_id, candidate_a.id, user_id, None)

    async with db_session.begin():
        await set_org(db_session, org_id)
        escalated_docs = await list_documents(db_session, escalated=True)
        assert [d.id for d in escalated_docs] == [doc_a]

        all_docs = await list_documents(db_session)
        assert {d.id for d in all_docs} == {doc_a, doc_b}


@pytest.mark.asyncio
async def test_list_documents_sort_low_confidence_first(db_session: AsyncSession) -> None:
    org_id, user_id = "org_esc_4", "usr_esc_4"
    quiet_doc, noisy_doc = new_id("doc"), new_id("doc")
    async with db_session.begin():
        await _seed_org_user(db_session, org_id, user_id)
        await _seed_document_with_manifest(db_session, org_id, user_id, quiet_doc)
        await _seed_document_with_manifest(db_session, org_id, user_id, noisy_doc)

    async with db_session.begin():
        await set_org(db_session, org_id)
        # noisy_doc gets two unresolved low-confidence candidates; quiet_doc gets none.
        for _ in range(2):
            candidate = RedactionCandidate(
                id=new_id("cand"), org_id=org_id, doc_id=noisy_doc, page_no=1,
                bbox={"x": 0, "y": 0, "w": 1, "h": 1}, display_text_encrypted="enc",
                origin="deterministic", confidence="low", state="suggested", detector_versions={},
            )
            db_session.add(candidate)

    async with db_session.begin():
        await set_org(db_session, org_id)
        ordered = await list_documents(db_session, sort="low_confidence_first")
        assert [d.id for d in ordered] == [noisy_doc, quiet_doc]
