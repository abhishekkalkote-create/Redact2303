import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.schemas.request import RequestCreate, RequestPatch
from app.services.request_service import create_request, get_request, list_requests, patch_request
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
async def test_create_and_get_request(db_session: AsyncSession) -> None:
    org_id, user_id = "org_req_1", "usr_req_1"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        created = await create_request(
            db_session, org_id, user_id,
            RequestCreate(title="Public records request #42", reference_no="PR-42"),
        )
        assert created.status == "open"
        assert created.title == "Public records request #42"

    async with db_session.begin():
        await set_org(db_session, org_id)
        fetched = await get_request(db_session, created.id)
        assert fetched.id == created.id
        assert fetched.reference_no == "PR-42"


@pytest.mark.asyncio
async def test_get_request_missing_raises_not_found(db_session: AsyncSession) -> None:
    org_id, user_id = "org_req_2", "usr_req_2"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        with pytest.raises(NotFoundError):
            await get_request(db_session, "req_does_not_exist")


@pytest.mark.asyncio
async def test_list_requests_orders_newest_first(db_session: AsyncSession) -> None:
    org_id, user_id = "org_req_3", "usr_req_3"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    # Separate transactions: created_at uses server_default=func.now(), which is
    # transaction-time in Postgres — two inserts in one transaction would tie.
    async with db_session.begin():
        await set_org(db_session, org_id)
        first = await create_request(db_session, org_id, user_id, RequestCreate(title="First"))

    async with db_session.begin():
        await set_org(db_session, org_id)
        second = await create_request(db_session, org_id, user_id, RequestCreate(title="Second"))

    async with db_session.begin():
        await set_org(db_session, org_id)
        requests = await list_requests(db_session)
        ids = [r.id for r in requests]
        assert ids.index(second.id) < ids.index(first.id)


@pytest.mark.asyncio
async def test_patch_request_updates_fields_and_writes_audit_event(db_session: AsyncSession) -> None:
    org_id, user_id = "org_req_4", "usr_req_4"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        created = await create_request(db_session, org_id, user_id, RequestCreate(title="Original title"))

    async with db_session.begin():
        await set_org(db_session, org_id)
        updated = await patch_request(
            db_session, org_id, user_id, created.id, RequestPatch(title="Updated title", status="in_review"),
        )
        assert updated.title == "Updated title"
        assert updated.status == "in_review"

    async with db_session.begin():
        await set_org(db_session, org_id)
        result = await db_session.execute(
            text("SELECT action FROM audit_events WHERE object_type = 'request' AND object_id = :id ORDER BY id"),
            {"id": created.id},
        )
        actions = [row[0] for row in result.all()]
        assert actions == ["request.created", "request.updated"]
