"""specs/08-security-compliance.md § Support access model: "customer Agency Admin
approves a scoped, time-bound (<= 24h) grant; every access during grant writes
customer-visible audit events; grants listed in the org's audit UI." request_grant is the
platform-admin side (app/routers/platform.py); list_grants_for_org/decide_grant are the
org-admin side (app/routers/support_grants.py) — approval is the customer's call, never
the platform admin's own.

"No silent super-admin path exists in code — content endpoints check membership, not
platform role" still holds after this: nothing in this codebase currently checks an
active grant to unlock anything (there is no platform-admin content-viewing endpoint to
gate). This is pure request/approve/deny bookkeeping and an audit trail, ready for
whenever such a feature is deliberately built.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, NotFoundError
from app.core.ids import new_id
from app.db.session import org_session
from app.models.support_grant import SupportGrant
from app.services.audit_service import write_audit_event

MAX_GRANT_DURATION = timedelta(hours=24)


async def request_grant(platform_admin_user_id: str, org_id: str, reason: str) -> SupportGrant:
    async with org_session(org_id) as session:
        grant = SupportGrant(
            id=new_id("spgrt"), org_id=org_id, requested_by=platform_admin_user_id,
            reason=reason, status="requested", requested_at=datetime.now(UTC),
        )
        session.add(grant)
        await session.flush()
        await write_audit_event(
            session, org_id=org_id, actor_type="platform_admin", actor_id=platform_admin_user_id,
            action="support_grant.requested", object_type="support_grant", object_id=grant.id,
            metadata={"reason": reason},
        )
        await session.flush()
        await session.refresh(grant)
        return grant


async def list_grants_for_org(session: AsyncSession, org_id: str) -> list[SupportGrant]:
    result = await session.execute(
        select(SupportGrant).where(SupportGrant.org_id == org_id).order_by(SupportGrant.requested_at.desc())
    )
    return list(result.scalars().all())


async def decide_grant(session: AsyncSession, org_id: str, grant_id: str, decided_by: str, *, approve: bool) -> SupportGrant:
    grant = await session.get(SupportGrant, grant_id)
    if grant is None or grant.org_id != org_id:
        raise NotFoundError("Support grant not found")
    if grant.status != "requested":
        raise ApiError(409, "Conflict", f"Grant already decided (status: {grant.status})")

    now = datetime.now(UTC)
    grant.status = "approved" if approve else "denied"
    grant.decided_by = decided_by
    grant.decided_at = now
    if approve:
        grant.expires_at = now + MAX_GRANT_DURATION

    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=decided_by,
        action="support_grant.approved" if approve else "support_grant.denied",
        object_type="support_grant", object_id=grant.id, metadata={"reason": grant.reason},
    )
    await session.flush()
    await session.refresh(grant)
    return grant
