"""app/services/billing_service.py. create_checkout_session/create_portal_session never
touch the DB (they only read org.stripe_customer_id and delegate to the configured
provider) so they're tested against a bare in-memory Organization. _apply_billing_event
takes an org-scoped session directly, so it's tested against the real test database via
the db_session fixture — no need for the AsyncSessionLocal monkeypatch that
parse_and_apply_billing_event's self-managed session would require (that wrapper is
exercised end-to-end instead, at the router layer, in test_billing_webhooks_router.py).
"""

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.provider import BillingEvent, BillingInvoice
from app.core.errors import ApiError, NotFoundError
from app.models.invoice import Invoice
from app.models.organization import Organization
from app.services.billing_service import (
    _apply_billing_event,
    create_checkout_session,
    create_portal_session,
)
from tests.conftest import set_org


async def _create_org(session: AsyncSession, org_id: str, *, plan: str = "pilot", plan_status: str = "trialing") -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings, stripe_customer_id) VALUES "
            "(:id, :id, :id, 'WA', 'other', :plan, :plan_status, '{}', :customer_id)"
        ),
        {"id": org_id, "plan": plan, "plan_status": plan_status, "customer_id": f"cus_{org_id}"},
    )


@pytest.mark.asyncio
async def test_create_checkout_session_rejects_org_with_no_billing_customer() -> None:
    org = Organization(id="org_x", stripe_customer_id=None)
    with pytest.raises(ApiError) as exc_info:
        await create_checkout_session(org, "growth", "https://x/success", "https://x/cancel")
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_create_checkout_session_delegates_to_the_configured_provider() -> None:
    org = Organization(id="org_x", stripe_customer_id="cus_x")
    session = await create_checkout_session(org, "growth", "https://x/success", "https://x/cancel")
    assert session.url.startswith("https://x/success?")


@pytest.mark.asyncio
async def test_create_portal_session_rejects_org_with_no_billing_customer() -> None:
    org = Organization(id="org_x", stripe_customer_id=None)
    with pytest.raises(ApiError) as exc_info:
        await create_portal_session(org, "https://x/settings")
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_apply_billing_event_checkout_completed_sets_plan_and_activates(db_session: AsyncSession) -> None:
    org_id = "org_bill_checkout"
    async with db_session.begin():
        await _create_org(db_session, org_id, plan="pilot", plan_status="trialing")

    async with db_session.begin():
        await set_org(db_session, org_id)
        await _apply_billing_event(db_session, BillingEvent(type="checkout.completed", org_id=org_id, plan="growth"))

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        assert org.plan == "growth"
        assert org.plan_status == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "expected_status"),
    [("invoice.paid", "active"), ("invoice.payment_failed", "past_due"), ("subscription.canceled", "canceled")],
)
async def test_apply_billing_event_drives_the_plan_status_state_machine(
    db_session: AsyncSession, event_type: str, expected_status: str
) -> None:
    org_id = f"org_bill_{event_type.replace('.', '_')}"
    async with db_session.begin():
        await _create_org(db_session, org_id, plan="growth", plan_status="past_due")

    async with db_session.begin():
        await set_org(db_session, org_id)
        await _apply_billing_event(db_session, BillingEvent(type=event_type, org_id=org_id))

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        assert org.plan_status == expected_status


@pytest.mark.asyncio
async def test_apply_billing_event_unknown_org_raises_not_found(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await set_org(db_session, "org_bill_missing")
        with pytest.raises(NotFoundError):
            await _apply_billing_event(db_session, BillingEvent(type="invoice.paid", org_id="org_bill_missing"))


@pytest.mark.asyncio
async def test_apply_billing_event_upserts_invoice_idempotently(db_session: AsyncSession) -> None:
    """specs/09-admin-billing.md: "webhook handlers idempotent" — replaying the same
    provider invoice id must update the one row, never create a duplicate."""
    org_id = "org_bill_invoice"
    async with db_session.begin():
        await _create_org(db_session, org_id)

    invoice = BillingInvoice(
        provider_invoice_id="in_replay_test", period="2026-08", status="open", line_items=[{"amount": 79900}]
    )
    async with db_session.begin():
        await set_org(db_session, org_id)
        await _apply_billing_event(db_session, BillingEvent(type="invoice.paid", org_id=org_id, invoice=invoice))

    updated_invoice = BillingInvoice(
        provider_invoice_id="in_replay_test", period="2026-08", status="paid", line_items=[{"amount": 79900}]
    )
    async with db_session.begin():
        await set_org(db_session, org_id)
        await _apply_billing_event(db_session, BillingEvent(type="invoice.paid", org_id=org_id, invoice=updated_invoice))

    async with db_session.begin():
        await set_org(db_session, org_id)
        result = await db_session.execute(select(Invoice).where(Invoice.org_id == org_id))
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "paid"
