"""app/services/usage_service.py. All these functions take a session directly, so they're
tested against the real test database via the db_session fixture — no AsyncSessionLocal
monkeypatch needed (unlike app/routers/internal_cron.py's handlers, which manage their own
sessions to sweep every org)."""

from datetime import UTC, datetime, timedelta
from typing import Self

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.ids import new_id
from app.models.organization import Organization
from app.services import webhook_service
from app.services.usage_service import (
    aggregate_and_report_usage,
    check_pilot_page_cap,
    check_usage_thresholds,
    get_usage_current,
    list_usage_records,
)
from tests.conftest import set_org


async def _create_org(session: AsyncSession, org_id: str, *, plan: str = "starter") -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings, stripe_customer_id) VALUES "
            "(:id, :id, :id, 'WA', 'other', :plan, 'active', '{}', :customer_id)"
        ),
        {"id": org_id, "plan": plan, "customer_id": f"cus_{org_id}"},
    )


async def _create_user_and_doc(session: AsyncSession, org_id: str, user_id: str, doc_id: str) -> None:
    await session.execute(
        text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )
    await session.execute(
        text(
            "INSERT INTO documents (id, org_id, filename, mime_type, source, status, uploaded_by, content_sha256) "
            "VALUES (:id, :org_id, 'x.pdf', 'application/pdf', 'upload', 'ready_for_review', :user_id, 'deadbeef')"
        ),
        {"id": doc_id, "org_id": org_id, "user_id": user_id},
    )


def _usage_record(org_id: str, *, metric: str, quantity: int, period: str, doc_id: str | None = None, reported: bool = False):
    return {
        "id": new_id("use"), "org_id": org_id, "metric": metric, "quantity": quantity, "doc_id": doc_id,
        "job_id": None, "occurred_at": datetime.now(UTC), "billing_period": period,
        "reported_to_billing_at": datetime.now(UTC) if reported else None,
    }


async def _insert_usage_records(session: AsyncSession, records: list[dict]) -> None:
    await session.execute(
        text(
            "INSERT INTO usage_records (id, org_id, metric, quantity, doc_id, job_id, occurred_at, "
            "billing_period, reported_to_billing_at) VALUES "
            "(:id, :org_id, :metric, :quantity, :doc_id, :job_id, :occurred_at, :billing_period, :reported_to_billing_at)"
        ),
        records,
    )


@pytest.mark.asyncio
async def test_get_usage_current_computes_totals_and_overage(db_session: AsyncSession) -> None:
    org_id = "org_usage_a"
    now = datetime(2026, 8, 15, tzinfo=UTC)
    async with db_session.begin():
        await _create_org(db_session, org_id, plan="starter")  # 2,500 pages included, $12/100 overage
        await _insert_usage_records(
            db_session,
            [
                _usage_record(org_id, metric="pages_processed", quantity=2600, period="2026-08"),
                _usage_record(org_id, metric="documents", quantity=3, period="2026-08"),
            ],
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        usage = await get_usage_current(db_session, org, now)

    assert usage["pages_used"] == 2600
    assert usage["pages_included"] == 2500
    assert usage["overage_pages"] == 100
    assert usage["overage_cost_cents"] == 1200  # one full 100-page overage unit at $12
    assert usage["totals_by_metric"]["documents"] == 3


@pytest.mark.asyncio
async def test_get_usage_current_pilot_cap_is_cumulative_not_monthly(db_session: AsyncSession) -> None:
    """specs/09-admin-billing.md: Pilot's "1,000 total cap" spans the whole trial, not a
    single month — usage from an earlier billing_period must still count."""
    org_id = "org_usage_pilot"
    now = datetime(2026, 8, 15, tzinfo=UTC)
    async with db_session.begin():
        await _create_org(db_session, org_id, plan="pilot")
        await _insert_usage_records(
            db_session,
            [
                _usage_record(org_id, metric="pages_processed", quantity=400, period="2026-07"),
                _usage_record(org_id, metric="pages_processed", quantity=300, period="2026-08"),
            ],
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        usage = await get_usage_current(db_session, org, now)

    assert usage["pages_used"] == 700
    assert usage["cap_kind"] == "total"


@pytest.mark.asyncio
async def test_get_usage_current_per_user_breakdown(db_session: AsyncSession) -> None:
    org_id = "org_usage_perusr"
    now = datetime(2026, 8, 15, tzinfo=UTC)
    async with db_session.begin():
        await _create_org(db_session, org_id)
        await _create_user_and_doc(db_session, org_id, "usr_a", "doc_a")
        await _create_user_and_doc(db_session, org_id, "usr_b", "doc_b")
        await _insert_usage_records(
            db_session,
            [
                _usage_record(org_id, metric="pages_processed", quantity=50, period="2026-08", doc_id="doc_a"),
                _usage_record(org_id, metric="pages_processed", quantity=20, period="2026-08", doc_id="doc_b"),
            ],
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        usage = await get_usage_current(db_session, org, now)

    by_user = {row["user_id"]: row["pages_processed"] for row in usage["per_user_breakdown"]}
    assert by_user == {"usr_a": 50, "usr_b": 20}


@pytest.mark.asyncio
async def test_list_usage_records_filters_by_period(db_session: AsyncSession) -> None:
    org_id = "org_usage_records"
    async with db_session.begin():
        await _create_org(db_session, org_id)
        await _insert_usage_records(
            db_session,
            [
                _usage_record(org_id, metric="pages_processed", quantity=10, period="2026-07"),
                _usage_record(org_id, metric="pages_processed", quantity=20, period="2026-08"),
            ],
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        records = await list_usage_records(db_session, org_id, "2026-08")

    assert len(records) == 1
    assert records[0].quantity == 20


@pytest.mark.asyncio
async def test_aggregate_and_report_usage_is_idempotent(db_session: AsyncSession) -> None:
    org_id = "org_usage_aggregate"
    now = datetime(2026, 8, 15, tzinfo=UTC)
    async with db_session.begin():
        await _create_org(db_session, org_id)
        await _insert_usage_records(
            db_session,
            [
                _usage_record(org_id, metric="pages_processed", quantity=100, period="2026-08"),
                _usage_record(org_id, metric="pages_processed", quantity=50, period="2026-08", reported=True),
            ],
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        first_run = await aggregate_and_report_usage(db_session, org_id, now)
    assert first_run == 1  # only the unreported record

    async with db_session.begin():
        await set_org(db_session, org_id)
        second_run = await aggregate_and_report_usage(db_session, org_id, now)
    assert second_run == 0  # already reported — never double-reports


class _FakeResponse:
    status_code = 200


class _FakeAsyncClient:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(self, *args: object, **kwargs: object) -> _FakeResponse:
        return _FakeResponse()


async def _create_subscription_for_threshold_events(session: AsyncSession, org_id: str) -> None:
    from app.crypto.envelope import get_cipher

    user_id = f"usr_{org_id}"
    await session.execute(
        text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )
    await session.execute(
        text(
            "INSERT INTO webhook_subscriptions (id, org_id, url, secret_encrypted, events, status, created_by) "
            "VALUES (:id, :org_id, 'https://example.com/hook', :secret, "
            "'[\"usage.threshold_80\", \"usage.threshold_95\"]', 'active', :user_id)"
        ),
        {"id": f"whsub_{org_id}", "org_id": org_id, "secret": get_cipher().encrypt(org_id, "whsec_test"), "user_id": user_id},
    )


@pytest.mark.asyncio
async def test_check_usage_thresholds_fires_once_per_period(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webhook_service.httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient())

    org_id = "org_usage_threshold"
    now = datetime(2026, 8, 15, tzinfo=UTC)
    async with db_session.begin():
        await _create_org(db_session, org_id, plan="starter")  # 2,500 included
        await _create_subscription_for_threshold_events(db_session, org_id)
        await _insert_usage_records(
            db_session, [_usage_record(org_id, metric="pages_processed", quantity=2100, period="2026-08")]  # 84%
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        first_fired = await check_usage_thresholds(db_session, org, now)
    assert first_fired == ["usage.threshold_80"]

    async with db_session.begin():
        await set_org(db_session, org_id)
        result = await db_session.execute(text("SELECT count(*) FROM webhook_deliveries WHERE event = 'usage.threshold_80'"))
        assert result.scalar_one() == 1

    # Same tick again later the same day — must not re-fire.
    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        second_fired = await check_usage_thresholds(db_session, org, now + timedelta(hours=6))
    assert second_fired == []


@pytest.mark.asyncio
async def test_check_usage_thresholds_skips_custom_allowance_plans(db_session: AsyncSession) -> None:
    org_id = "org_usage_enterprise"
    now = datetime(2026, 8, 15, tzinfo=UTC)
    async with db_session.begin():
        await _create_org(db_session, org_id, plan="enterprise")

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        fired = await check_usage_thresholds(db_session, org, now)
    assert fired == []


@pytest.mark.asyncio
async def test_check_pilot_page_cap_allows_processing_under_the_cap(db_session: AsyncSession) -> None:
    org_id = "org_pilot_cap_ok"
    async with db_session.begin():
        await _create_org(db_session, org_id, plan="pilot")
        await _insert_usage_records(db_session, [_usage_record(org_id, metric="pages_processed", quantity=999, period="2026-08")])

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        await check_pilot_page_cap(db_session, org)  # must not raise


@pytest.mark.asyncio
async def test_check_pilot_page_cap_blocks_processing_at_the_cap(db_session: AsyncSession) -> None:
    org_id = "org_pilot_cap_hit"
    async with db_session.begin():
        await _create_org(db_session, org_id, plan="pilot")
        await _insert_usage_records(db_session, [_usage_record(org_id, metric="pages_processed", quantity=1000, period="2026-08")])

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        with pytest.raises(ApiError) as exc_info:
            await check_pilot_page_cap(db_session, org)
    assert exc_info.value.status_code == 402


@pytest.mark.asyncio
async def test_check_pilot_page_cap_never_blocks_paid_plans(db_session: AsyncSession) -> None:
    """specs/09-admin-billing.md: every paid tier soft-continues and bills overage
    instead — only Pilot hard-blocks."""
    org_id = "org_pilot_cap_paid"
    async with db_session.begin():
        await _create_org(db_session, org_id, plan="growth")
        await _insert_usage_records(
            db_session, [_usage_record(org_id, metric="pages_processed", quantity=50_000, period="2026-08")]
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        await check_pilot_page_cap(db_session, org)  # must not raise
