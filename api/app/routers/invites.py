from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user, get_org_db, require_role
from app.models.membership import Membership
from app.models.user import User
from app.schemas.membership import InviteCreate, InviteOut
from app.services.invite_service import accept_invite, create_invite

router = APIRouter(tags=["invites"])


@router.post("/orgs/current/invites", response_model=InviteOut, status_code=201)
async def invite_member(
    payload: InviteCreate,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> InviteOut:
    invite, token = await create_invite(
        db, org_id=membership.org_id, invited_by=membership.user_id,
        email=payload.email, role=payload.role,
    )
    # TODO(Phase 3+): send via email provider instead of returning the raw token.
    result = InviteOut.model_validate(invite)
    result.token = token
    return result


@router.post("/invites/{token}/accept", response_model=dict)
async def accept_invite_route(token: str, user: User = Depends(get_current_user)) -> dict:
    membership = await accept_invite(token, user)
    return {"org_id": membership.org_id, "role": membership.role, "status": membership.status}
