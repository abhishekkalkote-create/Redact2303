from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.membership import Membership
from app.models.user import User


async def list_members(session: AsyncSession) -> list[tuple[Membership, User]]:
    """`session` is org-scoped (get_org_db) so RLS already limits `memberships` to this org;
    `users` is global, joined explicitly."""
    result = await session.execute(
        select(Membership, User).join(User, User.id == Membership.user_id)
    )
    return [(m, u) for m, u in result.all()]


async def update_member(
    session: AsyncSession, membership_id: str, role: str | None, status: str | None
) -> Membership:
    result = await session.execute(select(Membership).where(Membership.id == membership_id))
    membership = result.scalar_one_or_none()
    if membership is None:
        raise NotFoundError("Member not found")
    if role is not None:
        membership.role = role
    if status is not None:
        membership.status = status
    # See invite_service.create_invite: `session` is already inside a transaction owned by
    # the router's get_org_db dependency — flush, don't commit.
    await session.flush()
    await session.refresh(membership)
    return membership
