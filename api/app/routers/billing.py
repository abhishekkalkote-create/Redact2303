"""specs/04-api-spec.md § Usage, billing, audit. Checkout/portal/usage-derived plan card
delegate to app/services/billing_service.py, which delegates to whichever
BillingProvider is configured (app/billing/provider.py) — this router never touches a
vendor SDK directly.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_membership, get_org_db, get_org_db_allow_suspended, require_role
from app.billing.plans import PLAN_CATALOG
from app.models.invoice import Invoice
from app.models.membership import Membership
from app.models.organization import Organization
from app.schemas.billing import (
    CheckoutRequest,
    CheckoutResponse,
    InvoiceOut,
    PlanCardOut,
    PortalRequest,
    PortalResponse,
)
from app.services.billing_service import create_checkout_session, create_portal_session
from app.services.usage_service import get_usage_current

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
    db: AsyncSession = Depends(get_org_db_allow_suspended),
) -> CheckoutResponse:
    org = await _get_current_org(db, membership)
    session = await create_checkout_session(org, payload.plan, payload.success_url, payload.cancel_url)
    return CheckoutResponse(checkout_url=session.url)


@router.post("/billing/portal", response_model=PortalResponse)
async def create_billing_portal(
    payload: PortalRequest,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db_allow_suspended),
) -> PortalResponse:
    org = await _get_current_org(db, membership)
    portal_url = await create_portal_session(org, payload.return_url)
    return PortalResponse(portal_url=portal_url)


@router.get("/billing/plan", response_model=PlanCardOut)
async def get_billing_plan(
    membership: Membership = Depends(get_membership), db: AsyncSession = Depends(get_org_db)
) -> PlanCardOut:
    org = await _get_current_org(db, membership)
    catalog = PLAN_CATALOG[org.plan]
    usage = await get_usage_current(db, org, datetime.now(UTC))
    return PlanCardOut(
        plan=org.plan, plan_name=catalog.name, plan_status=org.plan_status,
        seats_included=catalog.seats_included, seats_active=usage["seats_active"],
        pages_included=catalog.pages_included,
    )


@router.get("/billing/invoices", response_model=list[InvoiceOut])
async def list_billing_invoices(db: AsyncSession = Depends(get_org_db)) -> list[Invoice]:
    result = await db.execute(select(Invoice).order_by(Invoice.created_at.desc()))
    return list(result.scalars().all())
