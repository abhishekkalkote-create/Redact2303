"""Migration 0007's asymmetric RLS on rule_packs/rule_set_versions/rules: any session
can SELECT a global row (org_id IS NULL) or its own org's rows; only a session with NO
org context set (migrations, the startup seed script) can INSERT a global row; a normal
org-scoped session can only insert its own org's rows — never another org's, never a
global one. Verified empirically per project convention, not assumed from reading the
policy SQL."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import set_org


async def _create_org(session: AsyncSession, org_id: str) -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'other', 'pilot', 'trialing', '{}')"
        ),
        {"id": org_id},
    )


@pytest.mark.asyncio
async def test_global_rule_pack_insertable_with_no_org_context_set(db_session: AsyncSession) -> None:
    """No set_org() call at all in this transaction — current_setting('app.org_id', true)
    is NULL, same as a migration or the seed script, not any org-scoped app request."""
    async with db_session.begin():
        await db_session.execute(
            text(
                "INSERT INTO rule_packs (id, org_id, name, category, status) VALUES "
                "('rpk_rls_global', NULL, 'Global Test Pack', 'custom', 'active')"
            )
        )

    async with db_session.begin():
        await _create_org(db_session, "org_rp_a")
        result = await db_session.execute(text("SELECT id FROM rule_packs WHERE id = 'rpk_rls_global'"))
        assert result.first() is not None, "any org-scoped session must see the global row"


@pytest.mark.asyncio
async def test_org_scoped_session_cannot_insert_a_global_rule_pack(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await _create_org(db_session, "org_rp_b")

    with pytest.raises(DBAPIError):
        async with db_session.begin():
            await set_org(db_session, "org_rp_b")
            await db_session.execute(
                text(
                    "INSERT INTO rule_packs (id, org_id, name, category, status) VALUES "
                    "('rpk_rls_sneaky', NULL, 'Sneaky Global Pack', 'custom', 'active')"
                )
            )


@pytest.mark.asyncio
async def test_org_scoped_session_cannot_insert_another_orgs_rule_pack(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await _create_org(db_session, "org_rp_c")
    async with db_session.begin():
        await _create_org(db_session, "org_rp_d")

    with pytest.raises(DBAPIError):
        async with db_session.begin():
            await set_org(db_session, "org_rp_c")
            await db_session.execute(
                text(
                    "INSERT INTO rule_packs (id, org_id, name, category, status) VALUES "
                    "('rpk_rls_cross', 'org_rp_d', 'Cross-Tenant Pack', 'custom', 'active')"
                )
            )


@pytest.mark.asyncio
async def test_org_sees_global_and_own_but_not_other_orgs_rule_packs(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await db_session.execute(
            text(
                "INSERT INTO rule_packs (id, org_id, name, category, status) VALUES "
                "('rpk_rls_starter', NULL, 'Starter Pack', 'core_pii', 'active')"
            )
        )
    async with db_session.begin():
        await _create_org(db_session, "org_rp_e")
        await db_session.execute(
            text(
                "INSERT INTO rule_packs (id, org_id, name, category, status) VALUES "
                "('rpk_rls_e_own', 'org_rp_e', 'Org E Custom Pack', 'custom', 'active')"
            )
        )
    async with db_session.begin():
        await _create_org(db_session, "org_rp_f")
        await db_session.execute(
            text(
                "INSERT INTO rule_packs (id, org_id, name, category, status) VALUES "
                "('rpk_rls_f_own', 'org_rp_f', 'Org F Custom Pack', 'custom', 'active')"
            )
        )

    async with db_session.begin():
        await set_org(db_session, "org_rp_e")
        result = await db_session.execute(text("SELECT id FROM rule_packs ORDER BY id"))
        visible = {row[0] for row in result.all()}
        assert visible == {"rpk_rls_starter", "rpk_rls_e_own"}, "must see global + own, never another org's"
