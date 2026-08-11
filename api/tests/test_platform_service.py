"""app/services/platform_service.py. Every function here manages its own session
(org_session/system_session) rather than taking one as a parameter — same as
app/services/org_service.py's create_org — so these go through
app/db/session.py's module-level AsyncSessionLocal singleton, which conftest.py's
autouse _point_app_db_at_test_database fixture points at the test database.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.services.platform_service import (
    get_cross_tenant_usage,
    get_org_for_platform,
    list_orgs_for_platform,
    provision_org,
    update_org_for_platform,
)
from tests.conftest import set_org

PLATFORM_ADMIN_USER_ID = "usr_platform_admin"


async def _insert_usage(session: AsyncSession, org_id: str, metric: str, quantity: int, period: str) -> None:
    await session.execute(
        text(
            "INSERT INTO usage_records (id, org_id, metric, quantity, occurred_at, billing_period) VALUES "
            "(:id, :org_id, :metric, :quantity, now(), :period)"
        ),
        {"id": new_id("use"), "org_id": org_id, "metric": metric, "quantity": quantity, "period": period},
    )


@pytest.mark.asyncio
async def test_provision_org_creates_org_and_sends_owner_invite(db_session: AsyncSession) -> None:
    # Invite.invited_by FKs to users.id — the platform admin "user" needs a row too,
    # even though they have no membership in the org being provisioned.
    async with db_session.begin():
        await db_session.execute(
            text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
            {"id": PLATFORM_ADMIN_USER_ID, "email": f"{PLATFORM_ADMIN_USER_ID}@example.com"},
        )

    org, invite_token = await provision_org(
        PLATFORM_ADMIN_USER_ID, name="Sales Assisted Org", jurisdiction_state="wa",
        org_type="county", plan="starter", owner_email="owner@example.com",
    )
    assert org.plan == "starter"
    assert org.plan_status == "trialing"
    assert org.jurisdiction_state == "WA"
    assert org.stripe_customer_id is not None
    assert invite_token is not None


@pytest.mark.asyncio
async def test_provision_org_without_owner_email_skips_invite() -> None:
    org, invite_token = await provision_org(
        PLATFORM_ADMIN_USER_ID, name="No Owner Yet Org", jurisdiction_state="WA",
        org_type="county", plan="pilot", owner_email=None,
    )
    assert org.id is not None
    assert invite_token is None


@pytest.mark.asyncio
async def test_list_and_get_org_for_platform_see_across_tenants() -> None:
    org_a, _ = await provision_org(
        PLATFORM_ADMIN_USER_ID, name="Org A", jurisdiction_state="WA", org_type="county", plan="pilot", owner_email=None
    )
    org_b, _ = await provision_org(
        PLATFORM_ADMIN_USER_ID, name="Org B", jurisdiction_state="CA", org_type="county", plan="pilot", owner_email=None
    )

    all_orgs = await list_orgs_for_platform()
    ids = {org.id for org in all_orgs}
    assert {org_a.id, org_b.id} <= ids

    fetched = await get_org_for_platform(org_a.id)
    assert fetched is not None
    assert fetched.id == org_a.id


@pytest.mark.asyncio
async def test_get_org_for_platform_returns_none_for_a_missing_org() -> None:
    assert await get_org_for_platform("org_does_not_exist") is None


@pytest.mark.asyncio
async def test_update_org_for_platform_changes_plan_status_and_plan() -> None:
    org, _ = await provision_org(
        PLATFORM_ADMIN_USER_ID, name="Suspend Me", jurisdiction_state="WA", org_type="county", plan="pilot", owner_email=None
    )

    updated = await update_org_for_platform(PLATFORM_ADMIN_USER_ID, org.id, {"plan": "growth", "plan_status": "suspended"})

    assert updated.plan == "growth"
    assert updated.plan_status == "suspended"


@pytest.mark.asyncio
async def test_update_org_for_platform_sets_page_cap_override_and_merges_features() -> None:
    org, _ = await provision_org(
        PLATFORM_ADMIN_USER_ID, name="Override Me", jurisdiction_state="WA", org_type="county", plan="pilot", owner_email=None
    )

    updated = await update_org_for_platform(
        PLATFORM_ADMIN_USER_ID, org.id, {"page_cap_override": 5000, "features": {"beta_feature": True}}
    )

    assert updated.settings["page_cap_override"] == 5000
    assert updated.settings["features"]["beta_feature"] is True
    # untouched defaults survive the merge
    assert "dual_approval_required" in updated.settings


@pytest.mark.asyncio
async def test_get_cross_tenant_usage_aggregates_pages_across_orgs(db_session: AsyncSession) -> None:
    now = datetime(2026, 8, 15, tzinfo=UTC)
    org_a, _ = await provision_org(
        PLATFORM_ADMIN_USER_ID, name="Usage Org A", jurisdiction_state="WA", org_type="county", plan="starter", owner_email=None
    )
    org_b, _ = await provision_org(
        PLATFORM_ADMIN_USER_ID, name="Usage Org B", jurisdiction_state="WA", org_type="county", plan="growth", owner_email=None
    )

    async with db_session.begin():
        await set_org(db_session, org_a.id)
        await _insert_usage(db_session, org_a.id, "pages_processed", 100, "2026-08")
    async with db_session.begin():
        await set_org(db_session, org_b.id)
        await _insert_usage(db_session, org_b.id, "pages_processed", 250, "2026-08")

    rollup = await get_cross_tenant_usage(now)

    by_id = {row["org_id"]: row for row in rollup["orgs"]}
    assert by_id[org_a.id]["pages_processed"] == 100
    assert by_id[org_b.id]["pages_processed"] == 250
    assert rollup["orgs"][0]["pages_processed"] >= rollup["orgs"][-1]["pages_processed"]  # sorted descending
