"""app/routers/internal_cron.py: shared-secret auth (not Cognito) gating a handler that
sweeps every org via app/db/session.py's new system_session(). Both are only observable
end-to-end through the real ASGI app, so these go through httpx against `app.main.app`
rather than calling the handler directly.

app/db/session.py's `engine`/`AsyncSessionLocal` are a module-level singleton bound to
`settings.database_url` (the dev database per .env, deliberately separate from
TEST_DATABASE_URL — see conftest.py's module docstring) — the router's own session
helpers (org_session/system_session) go through that singleton, not the db_session
fixture. Monkeypatching AsyncSessionLocal to a factory bound to the test engine points
every org_session()/system_session() call made during a test at the real test database,
same one db_session itself uses.
"""

from datetime import UTC, datetime, timedelta
from typing import Self

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.db.session as db_session_module
from app.core.config import get_settings
from app.crypto.envelope import get_cipher
from app.main import app
from app.services import webhook_service
from tests.conftest import set_org


@pytest.fixture(autouse=True)
def _point_app_db_at_test_database(db_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_session_module, "AsyncSessionLocal", async_sessionmaker(db_engine, expire_on_commit=False))


async def _seed_org_with_pending_retry(session: AsyncSession, org_id: str) -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'other', 'pilot', 'trialing', '{}')"
        ),
        {"id": org_id},
    )
    user_id = f"usr_{org_id}"
    await session.execute(
        text(
            "INSERT INTO users (id, email, name, status) VALUES "
            "(:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": f"{org_id}@example.com"},
    )
    sub_id = f"whsub_{org_id}"
    await session.execute(
        text(
            "INSERT INTO webhook_subscriptions (id, org_id, url, secret_encrypted, events, status, created_by) "
            "VALUES (:id, :org_id, 'https://example.com/hook', :secret, '[\"document.exported\"]', "
            "'active', :user_id)"
        ),
        {"id": sub_id, "org_id": org_id, "secret": get_cipher().encrypt(org_id, "whsec_test"), "user_id": user_id},
    )
    await session.execute(
        text(
            "INSERT INTO webhook_deliveries (id, org_id, subscription_id, event, payload, status, "
            "attempt_count, next_retry_at) VALUES "
            "(:id, :org_id, :sub_id, 'document.exported', '{}', 'failed', 1, :next_retry_at)"
        ),
        {
            "id": f"whdlv_{org_id}", "org_id": org_id, "sub_id": sub_id,
            "next_retry_at": datetime.now(UTC) - timedelta(minutes=5),
        },
    )


@pytest.mark.asyncio
async def test_webhook_retry_tick_rejects_missing_secret() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/internal/cron/webhook-retry")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_retry_tick_rejects_wrong_secret() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/internal/cron/webhook-retry", headers={"X-Internal-Cron-Secret": "not-it"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_retry_tick_sweeps_every_org(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two orgs each have one due-for-retry delivery; a single tick must retry both —
    proof that system_session() actually resolves every org, not just whichever one
    happens to be in context."""

    class _FakeResponse:
        status_code = 200

    class _FakeAsyncClient:
        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def post(self, *args: object, **kwargs: object) -> _FakeResponse:
            return _FakeResponse()

    monkeypatch.setattr(webhook_service.httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient())

    async with db_session.begin():
        await _seed_org_with_pending_retry(db_session, "org_cron_a")
    async with db_session.begin():
        await _seed_org_with_pending_retry(db_session, "org_cron_b")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/internal/cron/webhook-retry",
            headers={"X-Internal-Cron-Secret": get_settings().internal_cron_secret},
        )
    assert resp.status_code == 200
    assert resp.json() == {"deliveries_retried": 2}

    async with db_session.begin():
        await set_org(db_session, "org_cron_a")
        result = await db_session.execute(text("SELECT status FROM webhook_deliveries WHERE org_id = 'org_cron_a'"))
        assert result.scalar_one() == "success"
