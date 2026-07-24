import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.db.session import AsyncSessionLocal, org_session, user_session
from app.models.invite import Invite
from app.models.membership import Membership
from app.models.user import User
from app.services.audit_service import write_audit_event

INVITE_TTL_DAYS = 7


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_invite(
    session: AsyncSession, org_id: str, invited_by: str, email: str, role: str
) -> tuple[Invite, str]:
    token = secrets.token_urlsafe(32)
    invite = Invite(
        org_id=org_id,
        email=email.lower(),
        role=role,
        token_hash=_hash_token(token),
        invited_by=invited_by,
        expires_at=datetime.now(UTC) + timedelta(days=INVITE_TTL_DAYS),
    )
    session.add(invite)
    # `session` here is the router's Depends(get_org_db) session — already inside a
    # transaction owned by org_session; flush (not commit) and let that transaction's own
    # `async with` block commit on normal exit. Committing here would close the transaction
    # out from under the dependency and break any further use of `session` in this request.
    await session.flush()
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=invited_by,
        action="member.invited", object_type="invite", object_id=invite.id,
        metadata={"role": role},  # content-free: no email in audit metadata
    )
    await session.flush()
    await session.refresh(invite)
    return invite, token


async def _find_invite_by_token(token_hash: str) -> Invite | None:
    """Looks up an invite before we know which org it belongs to — RLS can't use the usual
    `org_id = app.org_id` policy here (we don't have an org_id yet). Instead `invites` carries
    a second, narrowly-scoped policy: a session that declares (via set_config) the exact
    token_hash it's asserting knowledge of may see *only* the one row matching that hash.
    Knowing the hash requires knowing the original 256-bit token, so this can't be used to
    enumerate other orgs' invites (see migration 0001 `invite_token_lookup` policy)."""
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.lookup_invite_token_hash', :h, true)"),
            {"h": token_hash},
        )
        result = await session.execute(select(Invite).where(Invite.token_hash == token_hash))
        return result.scalar_one_or_none()


async def accept_invite(token: str, user: User) -> Membership:
    token_hash = _hash_token(token)
    invite = await _find_invite_by_token(token_hash)
    if invite is None or invite.accepted_at is not None:
        raise NotFoundError("Invite not found or already used")
    if invite.expires_at < datetime.now(UTC):
        raise NotFoundError("Invite expired")
    if invite.email != user.email.lower():
        raise NotFoundError("Invite not found")

    # "One active org per user" must be checked across ALL orgs, not just invite.org_id —
    # an org-scoped session here would only ever see rows in invite.org_id (which is exactly
    # the org the user does NOT yet belong to), missing an existing membership elsewhere.
    async with user_session(user.id) as session:
        existing = await session.execute(
            select(Membership).where(Membership.user_id == user.id, Membership.status != "deactivated")
        )
        if existing.scalars().first() is not None:
            raise ConflictError("User already belongs to an organization (v1: one active org per user)")

    # Now that we know the org, do the actual writes under proper org context so RLS's
    # normal org_id = app.org_id policy applies — no special-casing for the writes.
    async with org_session(invite.org_id) as session:
        membership = Membership(
            org_id=invite.org_id, user_id=user.id, role=invite.role, status="active",
            invited_by=invite.invited_by,
        )
        session.add(membership)
        db_invite = await session.get(Invite, invite.id)
        assert db_invite is not None, "invite row disappeared between lookup and accept"
        db_invite.accepted_at = datetime.now(UTC)
        await write_audit_event(
            session, org_id=invite.org_id, actor_type="user", actor_id=user.id,
            action="member.invite_accepted", object_type="membership", object_id=membership.id,
            metadata={"role": invite.role},
        )
        await session.flush()
        await session.refresh(membership)
        return membership
