"""In-memory stand-in for Stripe (specs/02-architecture.md ADR-8) until real test-mode
credentials exist — see app/billing/provider.py's get_billing_provider(). No network
calls; customer/session ids are fabricated ULIDs. parse_webhook_event does not verify a
signature (there is no real signing secret in mock mode); it trusts the JSON body
verbatim, so it must never be selected outside env == "local"/tests (enforced by
get_billing_provider(), not here).
"""

import json

from app.billing.provider import BillingEvent, BillingInvoice, BillingProvider, CheckoutSession
from app.core.errors import ApiError
from app.core.ids import new_id


class MockBillingProvider(BillingProvider):
    async def create_customer(self, org_id: str, org_name: str, email: str) -> str:
        return new_id("cus")

    async def create_checkout_session(
        self, org_id: str, customer_id: str, plan: str, success_url: str, cancel_url: str
    ) -> CheckoutSession:
        session_id = new_id("cs")
        # No real card form to redirect to — land straight on the success URL, same as a
        # completed Stripe Checkout would, with enough on the query string for tests/manual
        # QA to correlate.
        return CheckoutSession(id=session_id, url=f"{success_url}?mock_checkout_session_id={session_id}&plan={plan}")

    async def create_portal_session(self, customer_id: str, return_url: str) -> str:
        return f"{return_url}?mock_portal_for={customer_id}"

    async def report_usage(self, customer_id: str, metric: str, quantity: int, period: str) -> None:
        return None

    def parse_webhook_event(self, payload: bytes, signature_header: str | None) -> BillingEvent:
        try:
            body = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ApiError(400, "Bad Request", "Malformed webhook payload") from exc

        event_type = body.get("type")
        org_id = body.get("org_id")
        if not event_type or not org_id:
            raise ApiError(400, "Bad Request", "Webhook payload missing type/org_id")

        invoice_data = body.get("invoice")
        invoice = (
            BillingInvoice(
                provider_invoice_id=invoice_data["id"],
                period=invoice_data["period"],
                status=invoice_data["status"],
                line_items=invoice_data.get("line_items", []),
                pdf_url=invoice_data.get("pdf_url"),
            )
            if invoice_data
            else None
        )
        return BillingEvent(type=event_type, org_id=org_id, plan=body.get("plan"), invoice=invoice)
