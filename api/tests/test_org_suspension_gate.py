"""app/auth/deps.py's get_org_db: specs/09-admin-billing.md "suspended (read-only: can
view/export nothing new)" — enforced once at this shared choke point (see get_org_db's
own docstring for why) rather than retrofitting every router.

Unit-tests the dependency function directly with a hand-built Membership + Request
rather than going through the full Cognito/dev-auth token flow — nothing in this test
suite exercises that flow yet (a separate, pre-existing gap, not something this test
needs to fill). get_org_db manages its own session via org_session(), which goes through
app/db/session.py's module-level AsyncSessionLocal singleton — same monkeypatch as
test_internal_cron.py.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

import app.db.session as db_session_module
from app.auth.deps import get_org_db, get_org_db_allow_suspended
from app.core.errors import ApiError
from app.models.membership import Membership
from tests.conftest import set_org


@pytest.fixture(autouse=True)
def _point_app_db_at_test_database(db_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_session_module, "AsyncSessionLocal", async_sessionmaker(db_engine, expire_on_commit=False))


def _request(method: str) -> Request:
    return Request(scope={"type": "http", "method": method, "headers": []})


async def _create_org(session: AsyncSession, org_id: str, plan_status: str) -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'other', 'starter', :plan_status, '{}')"
        ),
        {"id": org_id, "plan_status": plan_status},
    )


@pytest.mark.asyncio
async def test_get_org_db_blocks_writes_for_a_suspended_org(db_session: AsyncSession) -> None:
    org_id = "org_suspend_a"
    async with db_session.begin():
        await _create_org(db_session, org_id, "suspended")

    membership = Membership(org_id=org_id, user_id="usr_x", role="agency_admin", status="active")
    with pytest.raises(ApiError) as exc_info:
        async for _ in get_org_db(_request("POST"), membership):
            pass
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_org_db_allows_reads_for_a_suspended_org(db_session: AsyncSession) -> None:
    org_id = "org_suspend_b"
    async with db_session.begin():
        await _create_org(db_session, org_id, "suspended")

    membership = Membership(org_id=org_id, user_id="usr_x", role="agency_admin", status="active")
    async for session in get_org_db(_request("GET"), membership):
        assert session is not None
        break


@pytest.mark.asyncio
async def test_get_org_db_allows_writes_for_an_active_org(db_session: AsyncSession) -> None:
    org_id = "org_suspend_c"
    async with db_session.begin():
        await _create_org(db_session, org_id, "active")

    membership = Membership(org_id=org_id, user_id="usr_x", role="agency_admin", status="active")
    async for session in get_org_db(_request("POST"), membership):
        assert session is not None
        break


@pytest.mark.asyncio
async def test_get_org_db_allow_suspended_bypasses_the_gate(db_session: AsyncSession) -> None:
    """The escape hatch app/routers/billing.py's checkout/portal routes use — a
    suspended org must still be able to reach them to pay and reactivate."""
    org_id = "org_suspend_d"
    async with db_session.begin():
        await _create_org(db_session, org_id, "suspended")

    membership = Membership(org_id=org_id, user_id="usr_x", role="agency_admin", status="active")
    async for session in get_org_db_allow_suspended(membership):
        assert session is not None
        break
