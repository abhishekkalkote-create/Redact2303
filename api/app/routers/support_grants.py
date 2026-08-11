"""specs/08-security-compliance.md § Support access model: the customer's own side of a
support grant — approval is the Agency Admin's call, never the platform admin's. "grants
listed in the org's audit UI" is served here rather than a separate screen; the audit
trail itself (support_grant.requested/approved/denied) is already visible via the normal
GET /audit-events.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_membership, get_org_db, require_role
from app.models.membership import Membership
from app.schemas.support_grant import SupportGrantOut
from app.services.support_grant_service import decide_grant, list_grants_for_org

router = APIRouter(tags=["support-grants"])


@router.get("/orgs/current/support-grants", response_model=list[SupportGrantOut])
async def list_support_grants(
    membership: Membership = Depends(get_membership), db: AsyncSession = Depends(get_org_db)
) -> list[SupportGrantOut]:
    return [SupportGrantOut.from_support_grant(g) for g in await list_grants_for_org(db, membership.org_id)]


@router.post("/support-grants/{grant_id}/approve", response_model=SupportGrantOut)
async def approve_support_grant(
    grant_id: str, membership: Membership = Depends(require_role("agency_admin")), db: AsyncSession = Depends(get_org_db)
) -> SupportGrantOut:
    grant = await decide_grant(db, membership.org_id, grant_id, membership.user_id, approve=True)
    return SupportGrantOut.from_support_grant(grant)


@router.post("/support-grants/{grant_id}/deny", response_model=SupportGrantOut)
async def deny_support_grant(
    grant_id: str, membership: Membership = Depends(require_role("agency_admin")), db: AsyncSession = Depends(get_org_db)
) -> SupportGrantOut:
    grant = await decide_grant(db, membership.org_id, grant_id, membership.user_id, approve=False)
    return SupportGrantOut.from_support_grant(grant)
