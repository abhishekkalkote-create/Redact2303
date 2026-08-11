"""app/services/legal_hold_service.py. All functions take a session directly, tested
against the real test database via db_session."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.document import Document
from app.models.request import RecordsRequest
from app.services.legal_hold_service import (
    clear_document_legal_hold,
    clear_request_legal_hold,
    set_document_legal_hold,
    set_request_legal_hold,
)
from tests.conftest import set_org

ACTOR_ID = "usr_legal_hold_actor"


async def _create_org_user_doc_and_request(session: AsyncSession, org_id: str, doc_id: str, request_id: str) -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'other', 'starter', 'active', '{}')"
        ),
        {"id": org_id},
    )
    await session.execute(
        text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
        {"id": ACTOR_ID, "email": f"{ACTOR_ID}@example.com"},
    )
    await session.execute(
        text("INSERT INTO requests (id, org_id, title, status) VALUES (:id, :org_id, 'Request', 'open')"),
        {"id": request_id, "org_id": org_id},
    )
    await session.execute(
        text(
            "INSERT INTO documents (id, org_id, filename, mime_type, source, status, uploaded_by, "
            "content_sha256, request_id) VALUES "
            "(:id, :org_id, 'x.pdf', 'application/pdf', 'upload', 'ready_for_review', :user_id, 'deadbeef', :request_id)"
        ),
        {"id": doc_id, "org_id": org_id, "user_id": ACTOR_ID, "request_id": request_id},
    )


@pytest.mark.asyncio
async def test_set_and_clear_document_legal_hold(db_session: AsyncSession) -> None:
    org_id, doc_id, request_id = "org_lh_a", "doc_lh_a", "req_lh_a"
    async with db_session.begin():
        await _create_org_user_doc_and_request(db_session, org_id, doc_id, request_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        held = await set_document_legal_hold(db_session, org_id, ACTOR_ID, doc_id, "under litigation")
    assert held.legal_hold is True

    async with db_session.begin():
        await set_org(db_session, org_id)
        cleared = await clear_document_legal_hold(db_session, org_id, ACTOR_ID, doc_id, "case closed")
    assert cleared.legal_hold is False

    async with db_session.begin():
        await set_org(db_session, org_id)
        result = await db_session.execute(
            text("SELECT action FROM audit_events WHERE object_id = :id ORDER BY created_at"), {"id": doc_id}
        )
        actions = [row[0] for row in result.all()]
    assert actions == ["document.legal_hold_set", "document.legal_hold_cleared"]


@pytest.mark.asyncio
async def test_set_document_legal_hold_unknown_doc_raises_not_found(db_session: AsyncSession) -> None:
    org_id = "org_lh_b"
    async with db_session.begin():
        await set_org(db_session, org_id)
        await db_session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
                "plan, plan_status, settings) VALUES "
                "(:id, :id, :id, 'WA', 'other', 'starter', 'active', '{}')"
            ),
            {"id": org_id},
        )
        with pytest.raises(NotFoundError):
            await set_document_legal_hold(db_session, org_id, ACTOR_ID, "doc_missing", None)


@pytest.mark.asyncio
async def test_set_and_clear_request_legal_hold(db_session: AsyncSession) -> None:
    org_id, doc_id, request_id = "org_lh_c", "doc_lh_c", "req_lh_c"
    async with db_session.begin():
        await _create_org_user_doc_and_request(db_session, org_id, doc_id, request_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        held = await set_request_legal_hold(db_session, org_id, ACTOR_ID, request_id, "records request under appeal")
    assert held.legal_hold is True

    async with db_session.begin():
        await set_org(db_session, org_id)
        cleared = await clear_request_legal_hold(db_session, org_id, ACTOR_ID, request_id, None)
    assert cleared.legal_hold is False


@pytest.mark.asyncio
async def test_document_and_request_legal_hold_are_independent(db_session: AsyncSession) -> None:
    org_id, doc_id, request_id = "org_lh_d", "doc_lh_d", "req_lh_d"
    async with db_session.begin():
        await _create_org_user_doc_and_request(db_session, org_id, doc_id, request_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        await set_document_legal_hold(db_session, org_id, ACTOR_ID, doc_id, None)

    async with db_session.begin():
        await set_org(db_session, org_id)
        document = await db_session.get(Document, doc_id)
        request = await db_session.get(RecordsRequest, request_id)
        assert document is not None and document.legal_hold is True
        assert request is not None and request.legal_hold is False
