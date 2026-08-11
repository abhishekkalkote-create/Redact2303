"""specs/04-api-spec.md § Usage, billing, audit: self-serve checkout/portal. Delegates
entirely to app/services/billing_service.py, which delegates to whichever
BillingProvider is configured (app/billing/provider.py) — this router never touches a
vendor SDK directly.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_org_db, require_role
from app.models.membership import Membership
from app.models.organization import Organization
from app.schemas.billing import CheckoutRequest, CheckoutResponse, PortalRequest, PortalResponse
from app.services.billing_service import create_checkout_session, create_portal_session

router = APIRouter(tags=["billing"])


async def _get_current_org(db: AsyncSession, membership: Membership) -> Organization:
    org = await db.get(Organization, membership.org_id)
    # Same invariant as app/routers/orgs.py's _get_current_org: membership.org_id is
    # FK-constrained and both rows are read under the same org context.
    assert org is not None, f"membership {membership.id} references a missing org"
    return org


@router.post("/billing/checkout", response_model=CheckoutResponse)
async def create_billing_checkout(
    payload: CheckoutRequest,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> CheckoutResponse:
    org = await _get_current_org(db, membership)
    session = await create_checkout_session(org, payload.plan, payload.success_url, payload.cancel_url)
    return CheckoutResponse(checkout_url=session.url)


@router.post("/billing/portal", response_model=PortalResponse)
async def create_billing_portal(
    payload: PortalRequest,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> PortalResponse:
    org = await _get_current_org(db, membership)
    portal_url = await create_portal_session(org, payload.return_url)
    return PortalResponse(portal_url=portal_url)
