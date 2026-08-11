"""specs/04-api-spec.md § Usage, billing, audit. Checkout/portal/usage-derived plan card
delegate to app/services/billing_service.py, which delegates to whichever
BillingProvider is configured (app/billing/provider.py) — this router never touches a
vendor SDK directly.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
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
    PlanCatalogEntryOut,
    PortalRequest,
    PortalResponse,
    SuccessMetricsOut,
)
from app.services.billing_service import create_checkout_session, create_portal_session
from app.services.pilot_service import generate_roi_summary_pdf, get_success_metrics
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


@router.get("/billing/plans", response_model=list[PlanCatalogEntryOut])
async def list_billing_plan_catalog(_membership: Membership = Depends(get_membership)) -> list[PlanCatalogEntryOut]:
    """Published pricing (specs/09-admin-billing.md) — static, not org-specific; gated
    on being an authenticated member of some org, nothing more."""
    return [
        PlanCatalogEntryOut(
            key=key, name=entry.name, seats_included=entry.seats_included, cap_kind=entry.cap_kind,
            pages_included=entry.pages_included, price_cents_per_month=entry.price_cents_per_month,
            overage_price_per_100_pages_cents=entry.overage_price_per_100_pages_cents,
        )
        for key, entry in PLAN_CATALOG.items()
    ]


@router.get("/billing/success-metrics", response_model=SuccessMetricsOut)
async def get_billing_success_metrics(
    membership: Membership = Depends(get_membership), db: AsyncSession = Depends(get_org_db)
) -> SuccessMetricsOut:
    org = await _get_current_org(db, membership)
    return SuccessMetricsOut(**await get_success_metrics(db, org, datetime.now(UTC)))


@router.get("/billing/roi-summary")
async def get_billing_roi_summary(
    membership: Membership = Depends(get_membership), db: AsyncSession = Depends(get_org_db)
) -> Response:
    """specs/01-product-spec.md § Pilot playbook: "export-able one-page ROI summary
    (PDF) the champion can hand to their director." Not gated to Pilot orgs specifically
    — the same numbers are meaningful on any plan."""
    org = await _get_current_org(db, membership)
    now = datetime.now(UTC)
    metrics = await get_success_metrics(db, org, now)
    pdf_bytes = generate_roi_summary_pdf(org.name, metrics, now)
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=roi-summary.pdf"},
    )
