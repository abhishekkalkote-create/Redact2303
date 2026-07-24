import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit_service import list_audit_events, verify_chain, write_audit_event
from tests.conftest import set_org


async def _seed_org_and_user(session: AsyncSession, org_id: str, user_id: str) -> None:
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


@pytest.mark.asyncio
async def test_audit_chain_links_and_verifies(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await _seed_org_and_user(db_session, "org_audit_test", "usr_audit_test")

    async with db_session.begin():
        await set_org(db_session, "org_audit_test")
        e1 = await write_audit_event(
            db_session, org_id="org_audit_test", actor_type="user", actor_id="usr_audit_test",
            action="org.created", object_type="organization", object_id="org_audit_test",
        )
        e2 = await write_audit_event(
            db_session, org_id="org_audit_test", actor_type="user", actor_id="usr_audit_test",
            action="document.uploaded", object_type="document", object_id="doc_x",
        )
        assert e1.prev_hash is None
        assert e2.prev_hash == e1.hash
        assert e1.hash != e2.hash

    async with db_session.begin():
        await set_org(db_session, "org_audit_test")
        assert await verify_chain(db_session, "org_audit_test") is True


@pytest.mark.asyncio
async def test_audit_rejects_unknown_action(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await _seed_org_and_user(db_session, "org_audit_test2", "usr_audit_test2")

    async with db_session.begin():
        await set_org(db_session, "org_audit_test2")
        with pytest.raises(ValueError):
            await write_audit_event(
                db_session, org_id="org_audit_test2", actor_type="user", actor_id="usr_audit_test2",
                action="not.a.real.action", object_type="organization", object_id="org_audit_test2",
            )


@pytest.mark.asyncio
async def test_list_audit_events_filters_by_object_and_action(db_session: AsyncSession) -> None:
    """specs/04-api-spec.md GET /audit-events — object_type/object_id is also how the
    per-document timeline view (specs/07-ui-spec.md screen 7) is built."""
    org_id, user_id = "org_audit_query", "usr_audit_query"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        await write_audit_event(
            db_session, org_id=org_id, actor_type="user", actor_id=user_id,
            action="document.uploaded", object_type="document", object_id="doc_a",
        )
        await write_audit_event(
            db_session, org_id=org_id, actor_type="user", actor_id=user_id,
            action="review.completed", object_type="document", object_id="doc_a",
        )
        await write_audit_event(
            db_session, org_id=org_id, actor_type="user", actor_id=user_id,
            action="document.uploaded", object_type="document", object_id="doc_b",
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        for_doc_a = await list_audit_events(db_session, object_type="document", object_id="doc_a")
        assert [e.action for e in for_doc_a] == ["document.uploaded", "review.completed"]

        uploads_only = await list_audit_events(db_session, action="document.uploaded")
        assert {e.object_id for e in uploads_only} == {"doc_a", "doc_b"}

        nothing = await list_audit_events(db_session, object_type="document", object_id="doc_nonexistent")
        assert nothing == []


@pytest.mark.asyncio
async def test_audit_events_are_append_only(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await _seed_org_and_user(db_session, "org_audit_test3", "usr_audit_test3")

    async with db_session.begin():
        await set_org(db_session, "org_audit_test3")
        await write_audit_event(
            db_session, org_id="org_audit_test3", actor_type="user", actor_id="usr_audit_test3",
            action="org.created", object_type="organization", object_id="org_audit_test3",
        )

    with pytest.raises(DBAPIError):
        async with db_session.begin():
            await set_org(db_session, "org_audit_test3")
            await db_session.execute(
                text("UPDATE audit_events SET action = 'tampered' WHERE org_id = :org_id"),
                {"org_id": "org_audit_test3"},
            )
