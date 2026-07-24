"""RLS isolation test matrix (CI-mandatory, specs/03-data-model.md § RLS test matrix).

For each tenant table: a session scoped to org A must see zero rows and be unable to
insert rows belonging to org B. This is the test the build plan's Phase 0 AC requires
to pass "at the API, DB, S3 layers" — this file covers the DB layer.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import set_org, set_user


async def _create_org(session: AsyncSession, org_id: str, slug: str) -> None:
    """Mirrors app.services.org_service.create_org: app.org_id must equal the row's own id
    for the insert to satisfy the `organizations` tenant_isolation policy — a session can't
    declare a *different* org's id and insert on its behalf."""
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :name, :slug, 'WA', 'other', 'pilot', 'trialing', '{}')"
        ),
        {"id": org_id, "name": slug, "slug": slug},
    )


@pytest.mark.asyncio
async def test_org_a_cannot_read_org_b(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await _create_org(db_session, "org_a", "org-a-rls-test")
    async with db_session.begin():
        await _create_org(db_session, "org_b", "org-b-rls-test")

    async with db_session.begin():
        await set_org(db_session, "org_a")
        result = await db_session.execute(
            text("SELECT id FROM organizations WHERE id = 'org_b'")
        )
        assert result.first() is None, "org A must not see org B's row"

        result = await db_session.execute(text("SELECT id FROM organizations WHERE id = 'org_a'"))
        assert result.first() is not None, "org A must see its own row"


@pytest.mark.asyncio
async def test_membership_insert_for_other_org_is_blocked(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await _create_org(db_session, "org_c", "org-c-rls-test")
    async with db_session.begin():
        await set_org(db_session, "org_c")  # legitimate context, just for user bootstrap
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, status) VALUES "
                "('usr_rls_test', 'rls-test@example.com', 'RLS Test', 'active') "
                "ON CONFLICT (id) DO NOTHING"
            )
        )

    with pytest.raises(DBAPIError):
        async with db_session.begin():
            await set_org(db_session, "org_a")  # attacker context: not org_c
            await db_session.execute(
                text(
                    "INSERT INTO memberships (id, org_id, user_id, role, status) VALUES "
                    "('mem_rls_test', 'org_c', 'usr_rls_test', 'reviewer', 'active')"
                )
            )


@pytest.mark.asyncio
async def test_self_membership_lookup_is_scoped_to_caller(db_session: AsyncSession) -> None:
    """`self_membership_lookup` (migration 0001) must expose only the calling user's own
    rows — never another user's memberships, even across all orgs."""
    async with db_session.begin():
        await _create_org(db_session, "org_d", "org-d-rls-test")
    async with db_session.begin():
        await set_org(db_session, "org_d")
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, status) VALUES "
                "('usr_self_a', 'self-a@example.com', 'Self A', 'active'), "
                "('usr_self_b', 'self-b@example.com', 'Self B', 'active') "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        await db_session.execute(
            text(
                "INSERT INTO memberships (id, org_id, user_id, role, status) VALUES "
                "('mem_self_a', 'org_d', 'usr_self_a', 'reviewer', 'active'), "
                "('mem_self_b', 'org_d', 'usr_self_b', 'reviewer', 'active')"
            )
        )

    async with db_session.begin():
        await set_user(db_session, "usr_self_a")
        result = await db_session.execute(text("SELECT id FROM memberships"))
        ids = {row[0] for row in result.all()}
        assert ids == {"mem_self_a"}, "user A must see only their own membership row"
