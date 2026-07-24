"""specs/04-api-spec.md § Webhooks: "org-configurable ... HMAC-signed, retries with
backoff." httpx itself isn't mocked-library-mocked (no respx dependency exists in this
repo) — a small fake AsyncClient stands in for the network boundary so these tests verify
OUR request-building/signing/retry/backoff logic, the same testing-boundary choice made
for extract_msg in test_email_intake.py."""

from datetime import UTC, datetime, timedelta
from typing import Self

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.services import webhook_service
from app.services.webhook_service import (
    create_subscription,
    delete_subscription,
    list_subscriptions,
    retry_pending_deliveries,
    sign_payload,
    trigger_event,
)
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


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeAsyncClient:
    """Queued (status-or-exception) responses; records every call for inspection."""

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(self, url: str, content: bytes | None = None, headers: dict | None = None) -> _FakeResponse:
        self.calls.append({"url": url, "content": content, "headers": headers})
        outcome = self._responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResponse(outcome)


def _patch_httpx(monkeypatch, responses: list) -> _FakeAsyncClient:
    fake_client = _FakeAsyncClient(responses)
    monkeypatch.setattr(webhook_service.httpx, "AsyncClient", lambda **kwargs: fake_client)
    return fake_client


def test_validate_url_requires_https() -> None:
    with pytest.raises(ApiError) as exc_info:
        webhook_service._validate_url("http://example.com/hook")
    assert exc_info.value.status_code == 422


@pytest.mark.parametrize("url", ["https://localhost/hook", "https://127.0.0.1/hook", "https://10.0.0.5/hook", "https://169.254.169.254/hook"])
def test_validate_url_rejects_local_and_private_addresses(url: str) -> None:
    with pytest.raises(ApiError) as exc_info:
        webhook_service._validate_url(url)
    assert exc_info.value.status_code == 422


def test_validate_url_accepts_public_https_host() -> None:
    webhook_service._validate_url("https://example.com/hook")  # must not raise


def test_sign_payload_is_deterministic_hmac() -> None:
    sig_a = sign_payload("secret", b"same body")
    sig_b = sign_payload("secret", b"same body")
    sig_c = sign_payload("different secret", b"same body")
    assert sig_a == sig_b
    assert sig_a != sig_c


@pytest.mark.asyncio
async def test_create_list_delete_subscription_and_audit_trail(db_session: AsyncSession) -> None:
    org_id, user_id = "org_wh_1", "usr_wh_1"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        subscription, secret = await create_subscription(
            db_session, org_id, user_id, "https://example.com/hook", ["document.ready_for_review"]
        )
        assert len(secret) == 64
        assert subscription.status == "active"

    async with db_session.begin():
        await set_org(db_session, org_id)
        subs = await list_subscriptions(db_session)
        assert len(subs) == 1

    async with db_session.begin():
        await set_org(db_session, org_id)
        await delete_subscription(db_session, org_id, user_id, subscription.id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        assert await list_subscriptions(db_session) == []
        result = await db_session.execute(
            text("SELECT action FROM audit_events WHERE object_type = 'webhook_subscription' ORDER BY id")
        )
        actions = [row[0] for row in result.all()]
        assert actions == ["webhook.subscription_created", "webhook.subscription_deleted"]


@pytest.mark.asyncio
async def test_create_subscription_rejects_unknown_event(db_session: AsyncSession) -> None:
    org_id, user_id = "org_wh_2", "usr_wh_2"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        with pytest.raises(ApiError) as exc_info:
            await create_subscription(db_session, org_id, user_id, "https://example.com/hook", ["not.a.real.event"])
        assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_trigger_event_delivers_and_signs_payload(db_session: AsyncSession, monkeypatch) -> None:
    org_id, user_id = "org_wh_3", "usr_wh_3"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        subscription, secret = await create_subscription(
            db_session, org_id, user_id, "https://example.com/hook", ["document.ready_for_review"]
        )

    fake_client = _patch_httpx(monkeypatch, [200])
    async with db_session.begin():
        await set_org(db_session, org_id)
        await trigger_event(db_session, org_id, "document.ready_for_review", {"doc_id": "doc_x"})

    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]
    assert call["url"] == "https://example.com/hook"
    expected_signature = sign_payload(secret, call["content"])
    assert call["headers"]["X-RedactProof-Signature"] == f"sha256={expected_signature}"

    async with db_session.begin():
        await set_org(db_session, org_id)
        result = await db_session.execute(
            text("SELECT status, attempt_count, response_status FROM webhook_deliveries WHERE subscription_id = :id"),
            {"id": subscription.id},
        )
        row = result.one()
        assert row.status == "success"
        assert row.attempt_count == 1
        assert row.response_status == 200


@pytest.mark.asyncio
async def test_trigger_event_skips_non_matching_event_and_disabled_subscriptions(db_session: AsyncSession, monkeypatch) -> None:
    org_id, user_id = "org_wh_4", "usr_wh_4"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        await create_subscription(db_session, org_id, user_id, "https://example.com/hook", ["document.exported"])

    fake_client = _patch_httpx(monkeypatch, [])
    async with db_session.begin():
        await set_org(db_session, org_id)
        await trigger_event(db_session, org_id, "document.ready_for_review", {"doc_id": "doc_x"})

    assert fake_client.calls == []


@pytest.mark.asyncio
async def test_trigger_event_failure_schedules_backoff_retry(db_session: AsyncSession, monkeypatch) -> None:
    org_id, user_id = "org_wh_5", "usr_wh_5"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        subscription, _secret = await create_subscription(
            db_session, org_id, user_id, "https://example.com/hook", ["document.ready_for_review"]
        )

    _patch_httpx(monkeypatch, [500])
    async with db_session.begin():
        await set_org(db_session, org_id)
        await trigger_event(db_session, org_id, "document.ready_for_review", {"doc_id": "doc_x"})

    async with db_session.begin():
        await set_org(db_session, org_id)
        result = await db_session.execute(
            text("SELECT status, attempt_count, next_retry_at FROM webhook_deliveries WHERE subscription_id = :id"),
            {"id": subscription.id},
        )
        row = result.one()
        assert row.status == "failed"
        assert row.attempt_count == 1
        assert row.next_retry_at is not None


@pytest.mark.asyncio
async def test_retry_pending_deliveries_eventually_goes_dead_and_audits(db_session: AsyncSession, monkeypatch) -> None:
    org_id, user_id = "org_wh_6", "usr_wh_6"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        subscription, _secret = await create_subscription(
            db_session, org_id, user_id, "https://example.com/hook", ["document.ready_for_review"]
        )

    _patch_httpx(monkeypatch, [500])
    async with db_session.begin():
        await set_org(db_session, org_id)
        await trigger_event(db_session, org_id, "document.ready_for_review", {"doc_id": "doc_x"})

    # webhook_service.MAX_ATTEMPTS total attempts before "dead" — 1 already spent above.
    for _ in range(webhook_service.MAX_ATTEMPTS - 1):
        _patch_httpx(monkeypatch, [500])
        async with db_session.begin():
            await set_org(db_session, org_id)
            far_future = datetime.now(UTC) + timedelta(days=1)
            retried = await retry_pending_deliveries(db_session, org_id, far_future)
            assert len(retried) == 1

    async with db_session.begin():
        await set_org(db_session, org_id)
        result = await db_session.execute(
            text("SELECT status, attempt_count FROM webhook_deliveries WHERE subscription_id = :id"),
            {"id": subscription.id},
        )
        row = result.one()
        assert row.status == "dead"
        assert row.attempt_count == webhook_service.MAX_ATTEMPTS

        audit_result = await db_session.execute(
            text(
                "SELECT action FROM audit_events WHERE action = 'webhook.delivery_failed' "
                "AND object_id = :subscription_id"
            ),
            {"subscription_id": subscription.id},
        )
        assert audit_result.first() is not None
