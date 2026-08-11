"""app/services/support_grant_service.py. request_grant manages its own org_session
(same as app/services/platform_service.py — no membership to scope a normal session to);
list_grants_for_org/decide_grant take a session directly, tested against the real test
database via the db_session fixture.
"""

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, NotFoundError
from app.core.ids import new_id
from app.db.session import org_session
from app.services.support_grant_service import decide_grant, list_grants_for_org, request_grant
from tests.conftest import set_org

PLATFORM_ADMIN_USER_ID = "usr_platform_admin"


async def _create_org(session: AsyncSession, org_id: str) -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'other', 'starter', 'active', '{}')"
        ),
        {"id": org_id},
    )
    # request_grant's SupportGrant.requested_by FKs to users.id — the platform admin
    # "user" needs a row too, even though they have no membership in this org.
    await session.execute(
        text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
        {"id": PLATFORM_ADMIN_USER_ID, "email": f"{PLATFORM_ADMIN_USER_ID}@example.com"},
    )


async def _create_org_and_admin(session: AsyncSession, org_id: str, admin_user_id: str) -> None:
    await _create_org(session, org_id)
    await session.execute(
        text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
        {"id": admin_user_id, "email": f"{admin_user_id}@example.com"},
    )
    await session.execute(
        text(
            "INSERT INTO memberships (id, org_id, user_id, role, status) VALUES "
            "(:id, :org_id, :user_id, 'agency_admin', 'active')"
        ),
        {"id": new_id("mem"), "org_id": org_id, "user_id": admin_user_id},
    )


@pytest.mark.asyncio
async def test_request_grant_creates_a_requested_grant(db_session: AsyncSession) -> None:
    org_id = "org_grant_a"
    async with db_session.begin():
        await _create_org(db_session, org_id)

    grant = await request_grant(PLATFORM_ADMIN_USER_ID, org_id, "Investigating a customer-reported export bug")
    assert grant.org_id == org_id
    assert grant.status == "requested"
    assert grant.requested_by == PLATFORM_ADMIN_USER_ID
    assert grant.decided_at is None


@pytest.mark.asyncio
async def test_decide_grant_approve_sets_a_24h_expiry(db_session: AsyncSession) -> None:
    org_id, admin_id = "org_grant_b", "usr_grant_admin_b"
    async with db_session.begin():
        await _create_org_and_admin(db_session, org_id, admin_id)
    grant = await request_grant(PLATFORM_ADMIN_USER_ID, org_id, "reason")

    async with db_session.begin():
        await set_org(db_session, org_id)
        decided = await decide_grant(db_session, org_id, grant.id, admin_id, approve=True)

    assert decided.status == "approved"
    assert decided.decided_by == admin_id
    assert decided.expires_at is not None
    assert decided.decided_at is not None
    delta = decided.expires_at - decided.decided_at
    assert delta <= timedelta(hours=24)


@pytest.mark.asyncio
async def test_decide_grant_deny_sets_no_expiry(db_session: AsyncSession) -> None:
    org_id, admin_id = "org_grant_c", "usr_grant_admin_c"
    async with db_session.begin():
        await _create_org_and_admin(db_session, org_id, admin_id)
    grant = await request_grant(PLATFORM_ADMIN_USER_ID, org_id, "reason")

    async with db_session.begin():
        await set_org(db_session, org_id)
        decided = await decide_grant(db_session, org_id, grant.id, admin_id, approve=False)

    assert decided.status == "denied"
    assert decided.expires_at is None


@pytest.mark.asyncio
async def test_decide_grant_rejects_a_second_decision(db_session: AsyncSession) -> None:
    org_id, admin_id = "org_grant_d", "usr_grant_admin_d"
    async with db_session.begin():
        await _create_org_and_admin(db_session, org_id, admin_id)
    grant = await request_grant(PLATFORM_ADMIN_USER_ID, org_id, "reason")

    async with db_session.begin():
        await set_org(db_session, org_id)
        await decide_grant(db_session, org_id, grant.id, admin_id, approve=True)

    async with db_session.begin():
        await set_org(db_session, org_id)
        with pytest.raises(ApiError) as exc_info:
            await decide_grant(db_session, org_id, grant.id, admin_id, approve=False)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_decide_grant_unknown_id_raises_not_found(db_session: AsyncSession) -> None:
    org_id, admin_id = "org_grant_e", "usr_grant_admin_e"
    async with db_session.begin():
        await _create_org_and_admin(db_session, org_id, admin_id)
        with pytest.raises(NotFoundError):
            await decide_grant(db_session, org_id, "spgrt_missing", admin_id, approve=True)


@pytest.mark.asyncio
async def test_list_grants_for_org_is_scoped_to_its_own_org(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await _create_org(db_session, "org_grant_f")
    async with db_session.begin():
        await _create_org(db_session, "org_grant_g")

    grant_a = await request_grant(PLATFORM_ADMIN_USER_ID, "org_grant_f", "reason a")
    await request_grant(PLATFORM_ADMIN_USER_ID, "org_grant_g", "reason b")

    async with org_session("org_grant_f") as session:
        grants = await list_grants_for_org(session, "org_grant_f")

    assert [g.id for g in grants] == [grant_a.id]
