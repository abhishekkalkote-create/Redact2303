from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_membership, get_org_db, require_role
from app.models.membership import Membership
from app.models.user import User
from app.schemas.membership import MemberOut, MemberUpdate
from app.services.membership_service import list_members, update_member

router = APIRouter(prefix="/orgs/current/members", tags=["members"])


@router.get("/me", response_model=MemberOut)
async def get_my_membership(
    membership: Membership = Depends(get_membership), db: AsyncSession = Depends(get_org_db)
) -> MemberOut:
    """Lets the frontend know the current user's own role for this org (e.g. to show/hide
    the supervisor-only "Team queue" tab, specs/07-ui-spec.md screen 2) without decoding
    the JWT client-side."""
    user = await db.get(User, membership.user_id)
    return MemberOut(
        id=membership.id, user_id=membership.user_id, email=user.email if user else "",
        name=user.name if user else "", role=membership.role, status=membership.status,
    )


@router.get("", response_model=list[MemberOut])
async def list_org_members(
    # Viewing teammates is not a privileged action per specs/01-product-spec.md's roles
    # matrix — only "manage users & roles" (PATCH below) is agency_admin-only.
    db: AsyncSession = Depends(get_org_db),
) -> list[MemberOut]:
    rows = await list_members(db)
    return [
        MemberOut(
            id=m.id, user_id=u.id, email=u.email, name=u.name, role=m.role,
            status=m.status, last_active_at=u.last_active_at,
        )
        for m, u in rows
    ]


@router.patch("/{member_id}", response_model=MemberOut)
async def patch_member(
    member_id: str,
    payload: MemberUpdate,
    _=Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> MemberOut:
    membership = await update_member(db, member_id, payload.role, payload.status)
    user = await db.get(User, membership.user_id)
    return MemberOut(
        id=membership.id, user_id=membership.user_id, email=user.email if user else "",
        name=user.name if user else "", role=membership.role, status=membership.status,
    )
