"""specs/09-admin-billing.md § Billing mechanics: checkout/portal delegate straight to
the configured BillingProvider (app/billing/provider.py); parse_and_apply_billing_event
drives the plan_status state machine off its normalized webhook events — idempotent by
design (specs/09: "webhook handlers idempotent"): replaying the same event just
re-applies the same plan_status/invoice upsert, never a duplicate side effect.

The 14-day past_due -> suspended transition is time-based, not event-based (Stripe never
sends an event for "it's been 14 days") — it belongs in a scheduled check, not a webhook
handler; not built yet, left for a later Phase 5 slice.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.provider import BillingEvent, BillingInvoice, CheckoutSession, get_billing_provider
from app.core.errors import ApiError, NotFoundError
from app.core.ids import new_id
from app.db.session import org_session
from app.models.invoice import Invoice
from app.models.organization import Organization
from app.services.audit_service import write_audit_event

_STATUS_BY_EVENT_TYPE = {
    "invoice.paid": "active",
    "invoice.payment_failed": "past_due",
    "subscription.canceled": "canceled",
}
_AUDIT_ACTION_BY_EVENT_TYPE = {
    "checkout.completed": "billing.checkout_completed",
    "invoice.paid": "billing.payment_succeeded",
    "invoice.payment_failed": "billing.payment_failed",
    "subscription.canceled": "billing.subscription_canceled",
}


async def create_checkout_session(org: Organization, plan: str, success_url: str, cancel_url: str) -> CheckoutSession:
    if not org.stripe_customer_id:
        raise ApiError(409, "Conflict", "Organization has no billing customer on file")
    return await get_billing_provider().create_checkout_session(org.id, org.stripe_customer_id, plan, success_url, cancel_url)


async def create_portal_session(org: Organization, return_url: str) -> str:
    if not org.stripe_customer_id:
        raise ApiError(409, "Conflict", "Organization has no billing customer on file")
    return await get_billing_provider().create_portal_session(org.stripe_customer_id, return_url)


async def parse_and_apply_billing_event(payload: bytes, signature_header: str | None) -> None:
    """Manages its own org-scoped session (like app/services/org_service.py's
    create_org) rather than depending on a router-injected session — a webhook call has
    no membership to resolve get_org_db from; the org id comes from the event itself."""
    event = get_billing_provider().parse_webhook_event(payload, signature_header)
    async with org_session(event.org_id) as session:
        await _apply_billing_event(session, event)


async def _apply_billing_event(session: AsyncSession, event: BillingEvent) -> None:
    org = await session.get(Organization, event.org_id)
    if org is None:
        raise NotFoundError("Organization not found")

    if event.type == "checkout.completed":
        if event.plan:
            org.plan = event.plan
        org.plan_status = "active"
    elif event.type in _STATUS_BY_EVENT_TYPE:
        org.plan_status = _STATUS_BY_EVENT_TYPE[event.type]

    if event.invoice:
        await _upsert_invoice(session, org.id, event.invoice)

    action = _AUDIT_ACTION_BY_EVENT_TYPE.get(event.type)
    if action:
        await write_audit_event(
            session, org_id=org.id, actor_type="system", actor_id="billing_provider",
            action=action, object_type="organization", object_id=org.id,
            metadata={"plan": org.plan, "plan_status": org.plan_status},
        )
    await session.flush()


async def _upsert_invoice(session: AsyncSession, org_id: str, invoice: BillingInvoice) -> None:
    result = await session.execute(select(Invoice).where(Invoice.stripe_invoice_id == invoice.provider_invoice_id))
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.status = invoice.status
        existing.line_items = invoice.line_items
        existing.pdf_url = invoice.pdf_url
        existing.period = invoice.period
    else:
        session.add(
            Invoice(
                id=new_id("invc"), org_id=org_id, stripe_invoice_id=invoice.provider_invoice_id,
                period=invoice.period, line_items=invoice.line_items, status=invoice.status,
                pdf_url=invoice.pdf_url,
            )
        )
