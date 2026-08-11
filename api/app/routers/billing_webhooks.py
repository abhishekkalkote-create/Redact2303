"""Inbound from the billing provider (Stripe in prod) — not user-auth'd; the provider's
own signature verification (app/billing/provider.py's parse_webhook_event) is the trust
boundary here, same shape as app/routers/internal_cron.py's shared-secret boundary. Not
part of the public API surface: excluded from the OpenAPI schema the web app's TS client
is generated from, and mounted with no /v1 prefix (specs/04-api-spec.md's versioning is
for our own client, not something an external provider's fixed webhook URL follows).
"""

from fastapi import APIRouter, Request

from app.services.billing_service import parse_and_apply_billing_event

router = APIRouter(tags=["billing-webhooks"], include_in_schema=False)


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request) -> dict:
    payload = await request.body()
    signature_header = request.headers.get("Stripe-Signature")
    await parse_and_apply_billing_event(payload, signature_header)
    return {"received": True}
