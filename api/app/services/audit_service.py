"""specs/08-security-compliance.md § Audit integrity: append-only, per-org SHA-256 hash
chain (each row hashes canonical content + prev_hash). Call `write_audit_event` inside the
SAME transaction as the state change it describes — it doesn't manage its own transaction,
so the audit row and the action it records commit or roll back together.
"""

import hashlib
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.models.audit_event import AuditEvent

# Not exhaustive yet (spec says ~40 across all phases) — grows as each phase adds actions.
ACTIONS = frozenset(
    {
        "auth.login",
        "org.created",
        "member.invited",
        "member.invite_accepted",
        "member.role_changed",
        "document.uploaded",
        "document.processing_started",
        "document.ready_for_review",
        "document.processing_failed",
        "candidate.created",
        "candidate.approved",
        "candidate.rejected",
        "candidate.modified",
        "candidate.escalated",
        "candidate.escalation_resolved",
        "review.completed",
        "review.approved",
        "review.returned",
        "export.created",
        "export.integrity_failed",
        "export.downloaded",
        "request.created",
        "request.updated",
        "document.assigned",
        "webhook.subscription_created",
        "webhook.subscription_deleted",
        "rule_pack.created",
        "rule_set_version.drafted",
        "rule_set_version.published",
        "rule.created",
        "rule.updated",
        "rule.deleted",
        "rule_set_version.nl_edit_proposed",
        "webhook.delivered",
        "webhook.delivery_failed",
    }
)


def _canonical_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


async def write_audit_event(
    session: AsyncSession,
    *,
    org_id: str,
    actor_type: str,
    actor_id: str | None,
    action: str,
    object_type: str,
    object_id: str,
    metadata: dict | None = None,
) -> AuditEvent:
    if action not in ACTIONS:
        raise ValueError(f"Unknown audit action {action!r} — add it to ACTIONS")

    result = await session.execute(
        select(AuditEvent.hash)
        .where(AuditEvent.org_id == org_id)
        .order_by(AuditEvent.id.desc())
        .limit(1)
    )
    prev_hash = result.scalar_one_or_none()

    event_id = new_id("aud")
    canonical = _canonical_json(
        {
            "id": event_id,
            "org_id": org_id,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "action": action,
            "object_type": object_type,
            "object_id": object_id,
            "metadata": metadata or {},
        }
    )
    row_hash = hashlib.sha256((canonical + (prev_hash or "")).encode()).hexdigest()

    event = AuditEvent(
        id=event_id,
        org_id=org_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        metadata_=metadata or {},
        prev_hash=prev_hash,
        hash=row_hash,
    )
    session.add(event)
    await session.flush()
    return event


async def list_audit_events(
    session: AsyncSession,
    *,
    actor_id: str | None = None,
    action: str | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[AuditEvent]:
    """specs/04-api-spec.md GET /audit-events — the "Screen 7: Audit" filterable event
    stream, and (with object_type="document"&object_id=<id>) the per-document timeline
    view. Already org-scoped by RLS via the caller's org_session — no org_id filter needed
    here."""
    query = select(AuditEvent).order_by(AuditEvent.id)
    if actor_id:
        query = query.where(AuditEvent.actor_id == actor_id)
    if action:
        query = query.where(AuditEvent.action == action)
    if object_type:
        query = query.where(AuditEvent.object_type == object_type)
    if object_id:
        query = query.where(AuditEvent.object_id == object_id)
    if date_from:
        query = query.where(AuditEvent.created_at >= date_from)
    if date_to:
        query = query.where(AuditEvent.created_at <= date_to)
    result = await session.execute(query)
    return list(result.scalars().all())


async def verify_chain(session: AsyncSession, org_id: str) -> bool:
    """Nightly-job style verification (specs/08-security-compliance.md): recompute each
    row's hash from its canonical content + prev_hash and confirm it matches what's stored,
    and that each row's prev_hash matches the previous row's hash."""
    result = await session.execute(
        select(AuditEvent).where(AuditEvent.org_id == org_id).order_by(AuditEvent.id.asc())
    )
    rows = result.scalars().all()

    expected_prev: str | None = None
    for row in rows:
        if row.prev_hash != expected_prev:
            return False
        canonical = _canonical_json(
            {
                "id": row.id,
                "org_id": row.org_id,
                "actor_type": row.actor_type,
                "actor_id": row.actor_id,
                "action": row.action,
                "object_type": row.object_type,
                "object_id": row.object_id,
                "metadata": row.metadata_,
            }
        )
        expected_hash = hashlib.sha256((canonical + (row.prev_hash or "")).encode()).hexdigest()
        if expected_hash != row.hash:
            return False
        expected_prev = row.hash
    return True
