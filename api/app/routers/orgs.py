from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user, get_membership, get_org_db, require_role
from app.models.membership import Membership
from app.models.organization import Organization
from app.models.user import User
from app.schemas.organization import OrgCreate, OrgOut, OrgSettingsUpdate
from app.services.org_service import create_org

router = APIRouter(tags=["orgs"])


@router.post("/orgs", response_model=OrgOut, status_code=201)
async def create_organization(payload: OrgCreate, user: User = Depends(get_current_user)) -> Organization:
    return await create_org(user, payload)


async def _get_current_org(db: AsyncSession, membership: Membership) -> Organization:
    org = await db.get(Organization, membership.org_id)
    # membership.org_id is FK-constrained to organizations.id, and both rows are read under
    # the same org context — this can only be None if that invariant is somehow broken.
    assert org is not None, f"membership {membership.id} references a missing org"
    return org


@router.get("/orgs/current", response_model=OrgOut)
async def get_current_org(
    membership: Membership = Depends(get_membership), db: AsyncSession = Depends(get_org_db)
) -> Organization:
    return await _get_current_org(db, membership)


@router.patch("/orgs/current", response_model=OrgOut)
async def update_current_org(
    payload: OrgSettingsUpdate,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> Organization:
    org = await _get_current_org(db, membership)
    updates = payload.model_dump(exclude_none=True)
    if updates:
        org.settings = {**org.settings, **updates}
        # `db` is already inside a transaction owned by get_org_db — flush, don't commit
        # (see invite_service.create_invite for why).
        await db.flush()
        await db.refresh(org)
    return org
