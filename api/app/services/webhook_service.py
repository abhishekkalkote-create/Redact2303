"""specs/04-api-spec.md § Webhooks: "org-configurable ... HMAC-signed, retries with
backoff." Delivery is fired inline at the point of the state change it reports (same
place write_audit_event is called) — matches specs/05-redaction-pipeline.md's "notify
SSE + optional webhook" and this codebase's existing simplification of running the
pipeline synchronously in the API process rather than via real async workers
(app/pipeline/run.py's own docstring). trigger_event() never raises — a webhook
delivery failure must never fail the state change it's reporting.

retry_pending_deliveries() is real and correct but needs a periodic caller (a cron/ECS
task in prod, per specs/02-architecture.md's worker model) — nothing in this repo invokes
it on a schedule yet, same class of gap as the SQS queues infra/modules/queues
provisions with no consumer wired up.
"""

import hashlib
import hmac
import ipaddress
import json
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, NotFoundError
from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.models.webhook import SUPPORTED_EVENTS, WebhookDelivery, WebhookSubscription
from app.services.audit_service import write_audit_event

DELIVERY_TIMEOUT_SECONDS = 5.0
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 60  # 1m, 5m, 25m, 125m, then dead

# Bounded SSRF guard: rejects the obvious cases (literal loopback/private/link-local IPs,
# "localhost") by string/IP-literal inspection only — no DNS resolution, so it can't catch
# a hostname that resolves to a private address (DNS rebinding). That would need
# resolution-time validation at connect time, out of scope for this pass.
_BLOCKED_HOSTNAMES = {"localhost", "0.0.0.0"}


def _is_blocked_host(hostname: str) -> bool:
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        return True
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ApiError(422, "Unprocessable Entity", "Webhook URL must use https://")
    if not parsed.hostname or _is_blocked_host(parsed.hostname):
        raise ApiError(422, "Unprocessable Entity", "Webhook URL must not point at a local/private address")


def _validate_events(events: list[str]) -> None:
    unknown = set(events) - set(SUPPORTED_EVENTS)
    if not events or unknown:
        raise ApiError(422, "Unprocessable Entity", f"events must be a non-empty subset of {sorted(SUPPORTED_EVENTS)}")


async def create_subscription(
    session: AsyncSession, org_id: str, user_id: str, url: str, events: list[str]
) -> tuple[WebhookSubscription, str]:
    _validate_url(url)
    _validate_events(events)

    secret = secrets.token_hex(32)
    cipher = get_cipher()
    subscription = WebhookSubscription(
        id=new_id("whsub"), org_id=org_id, url=url, secret_encrypted=cipher.encrypt(org_id, secret),
        events=events, status="active", created_by=user_id,
    )
    session.add(subscription)
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="webhook.subscription_created", object_type="webhook_subscription", object_id=subscription.id,
        metadata={"url": url, "events": events},
    )
    await session.flush()
    await session.refresh(subscription)
    return subscription, secret


async def list_subscriptions(session: AsyncSession) -> list[WebhookSubscription]:
    result = await session.execute(select(WebhookSubscription).order_by(WebhookSubscription.created_at.desc()))
    return list(result.scalars().all())


async def delete_subscription(session: AsyncSession, org_id: str, user_id: str, subscription_id: str) -> None:
    subscription = await session.get(WebhookSubscription, subscription_id)
    if subscription is None:
        raise NotFoundError("Webhook subscription not found")
    await session.delete(subscription)
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="webhook.subscription_deleted", object_type="webhook_subscription", object_id=subscription_id,
        metadata={"url": subscription.url},
    )
    await session.flush()


def sign_payload(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _encode_envelope(event: str, org_id: str, data: dict) -> bytes:
    envelope = {"event": event, "org_id": org_id, "occurred_at": datetime.now(UTC).isoformat(), "data": data}
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()


async def _attempt_delivery(session: AsyncSession, delivery: WebhookDelivery, url: str, secret: str, body: bytes) -> None:
    delivery.attempt_count += 1
    delivery.last_attempted_at = datetime.now(UTC)
    signature = sign_payload(secret, body)
    try:
        async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url, content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-RedactProof-Signature": f"sha256={signature}",
                    "X-RedactProof-Delivery-Id": delivery.id,
                },
            )
        delivery.response_status = response.status_code
        if 200 <= response.status_code < 300:
            delivery.status = "success"
            delivery.next_retry_at = None
            return
        delivery.error = f"HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        delivery.error = str(exc)

    if delivery.attempt_count >= MAX_ATTEMPTS:
        delivery.status = "dead"
        delivery.next_retry_at = None
        # Worth an audit trail entry (unlike a transient retry) — an integration has
        # gone permanently dark and an admin should be able to see that in the log.
        await write_audit_event(
            session, org_id=delivery.org_id, actor_type="system", actor_id=None,
            action="webhook.delivery_failed", object_type="webhook_subscription", object_id=delivery.subscription_id,
            metadata={"delivery_id": delivery.id, "event": delivery.event, "attempts": delivery.attempt_count},
        )
    else:
        delivery.status = "failed"
        backoff = BACKOFF_BASE_SECONDS * (5 ** (delivery.attempt_count - 1))
        delivery.next_retry_at = datetime.now(UTC) + timedelta(seconds=backoff)


async def trigger_event(session: AsyncSession, org_id: str, event: str, data: dict) -> None:
    """Never raises — a webhook failure must not fail the state change it's reporting."""
    result = await session.execute(
        select(WebhookSubscription).where(WebhookSubscription.org_id == org_id, WebhookSubscription.status == "active")
    )
    subscriptions = [s for s in result.scalars().all() if event in s.events]
    if not subscriptions:
        return

    cipher = get_cipher()
    body = _encode_envelope(event, org_id, data)
    for subscription in subscriptions:
        delivery = WebhookDelivery(
            id=new_id("whdlv"), org_id=org_id, subscription_id=subscription.id,
            event=event, payload=data, status="pending", attempt_count=0,
        )
        session.add(delivery)
        try:
            secret = cipher.decrypt(org_id, subscription.secret_encrypted)
            await _attempt_delivery(session, delivery, subscription.url, secret, body)
        except Exception as exc:  # noqa: BLE001 — delivery is best-effort; never propagate
            delivery.status = "failed" if delivery.attempt_count < MAX_ATTEMPTS else "dead"
            delivery.error = str(exc)
    await session.flush()


async def retry_pending_deliveries(session: AsyncSession, org_id: str, now: datetime) -> list[WebhookDelivery]:
    """Needs a periodic caller (cron/ECS task) — see module docstring."""
    result = await session.execute(
        select(WebhookDelivery, WebhookSubscription)
        .join(WebhookSubscription, WebhookDelivery.subscription_id == WebhookSubscription.id)
        .where(
            WebhookDelivery.org_id == org_id, WebhookDelivery.status == "failed",
            WebhookDelivery.next_retry_at <= now,
        )
    )
    rows = result.all()

    cipher = get_cipher()
    retried = []
    for delivery, subscription in rows:
        body = _encode_envelope(delivery.event, org_id, delivery.payload)
        secret = cipher.decrypt(org_id, subscription.secret_encrypted)
        await _attempt_delivery(session, delivery, subscription.url, secret, body)
        retried.append(delivery)
    await session.flush()
    return retried
