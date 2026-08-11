"""Migration 0010's RLS on invoices: plain per-org isolation, no global-row nuance (unlike
rule_packs — see test_rule_pack_rls.py). Verified empirically per project convention, not
assumed from reading the policy SQL."""

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


async def _create_invoice(session: AsyncSession, invoice_id: str, org_id: str) -> None:
    await session.execute(
        text(
            "INSERT INTO invoices (id, org_id, period, line_items, status) VALUES "
            "(:id, :org_id, '2026-08', '[]', 'draft')"
        ),
        {"id": invoice_id, "org_id": org_id},
    )


@pytest.mark.asyncio
async def test_org_sees_only_its_own_invoices(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await _create_org(db_session, "org_invc_a")
        await _create_invoice(db_session, "invc_rls_a", "org_invc_a")
    async with db_session.begin():
        await _create_org(db_session, "org_invc_b")
        await _create_invoice(db_session, "invc_rls_b", "org_invc_b")

    async with db_session.begin():
        await set_org(db_session, "org_invc_a")
        result = await db_session.execute(text("SELECT id FROM invoices ORDER BY id"))
        visible = {row[0] for row in result.all()}
        assert visible == {"invc_rls_a"}, "must see only its own org's invoices"


@pytest.mark.asyncio
async def test_org_scoped_session_cannot_insert_another_orgs_invoice(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await _create_org(db_session, "org_invc_c")
    async with db_session.begin():
        await _create_org(db_session, "org_invc_d")

    with pytest.raises(DBAPIError):
        async with db_session.begin():
            await set_org(db_session, "org_invc_c")
            await _create_invoice(db_session, "invc_rls_cross", "org_invc_d")
