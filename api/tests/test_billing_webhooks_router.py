"""app/routers/billing_webhooks.py: the one place parse_and_apply_billing_event's
self-managed org_session() (app/services/billing_service.py) is actually exercised — its
transition logic itself is covered directly against the real test database in
test_billing_service.py's _apply_billing_event tests.

app/db/session.py's engine/AsyncSessionLocal are a module-level singleton bound to
settings.database_url (the dev database, deliberately separate from TEST_DATABASE_URL —
see conftest.py's module docstring); monkeypatching AsyncSessionLocal points the
webhook's self-managed org_session() at the real test database instead, same trick as
test_internal_cron.py.
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.db.session as db_session_module
from app.main import app
from tests.conftest import set_org


@pytest.fixture(autouse=True)
def _point_app_db_at_test_database(db_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_session_module, "AsyncSessionLocal", async_sessionmaker(db_engine, expire_on_commit=False))


@pytest.mark.asyncio
async def test_stripe_webhook_applies_the_event_end_to_end(db_session: AsyncSession) -> None:
    org_id = "org_whwebhook"
    async with db_session.begin():
        await set_org(db_session, org_id)
        await db_session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
                "plan, plan_status, settings, stripe_customer_id) VALUES "
                "(:id, :id, :id, 'WA', 'other', 'starter', 'trialing', '{}', 'cus_whwebhook')"
            ),
            {"id": org_id},
        )

    body = json.dumps({"type": "checkout.completed", "org_id": org_id, "plan": "growth"}).encode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/webhooks/stripe", content=body, headers={"Content-Type": "application/json"})
    assert resp.status_code == 200
    assert resp.json() == {"received": True}

    async with db_session.begin():
        await set_org(db_session, org_id)
        result = await db_session.execute(text("SELECT plan, plan_status FROM organizations WHERE id = :id"), {"id": org_id})
        row = result.one()
        assert row.plan == "growth"
        assert row.plan_status == "active"
