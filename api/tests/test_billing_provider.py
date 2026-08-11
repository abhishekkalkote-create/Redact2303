"""app/billing/mock_provider.py: no network, no DB — pure unit tests of the in-memory
stand-in used until real Stripe test-mode credentials exist (app/billing/provider.py's
get_billing_provider())."""

import json

import pytest

from app.billing.mock_provider import MockBillingProvider
from app.core.errors import ApiError


@pytest.fixture
def provider() -> MockBillingProvider:
    return MockBillingProvider()


@pytest.mark.asyncio
async def test_create_customer_returns_a_fabricated_id(provider: MockBillingProvider) -> None:
    customer_id = await provider.create_customer("org_x", "Test Org", "owner@example.com")
    assert customer_id.startswith("cus_")


@pytest.mark.asyncio
async def test_create_checkout_session_lands_on_the_success_url(provider: MockBillingProvider) -> None:
    session = await provider.create_checkout_session(
        "org_x", "cus_x", "growth", "https://app.example.com/billing/success", "https://app.example.com/billing/cancel"
    )
    assert session.url.startswith("https://app.example.com/billing/success?")
    assert "plan=growth" in session.url


@pytest.mark.asyncio
async def test_create_portal_session_returns_the_return_url(provider: MockBillingProvider) -> None:
    portal_url = await provider.create_portal_session("cus_x", "https://app.example.com/settings")
    assert portal_url.startswith("https://app.example.com/settings?")


def test_parse_webhook_event_normalizes_a_valid_payload(provider: MockBillingProvider) -> None:
    payload = json.dumps(
        {
            "type": "invoice.paid",
            "org_id": "org_x",
            "invoice": {
                "id": "in_123", "period": "2026-08", "status": "paid",
                "line_items": [{"description": "Growth plan", "amount": 79900}],
                "pdf_url": "https://example.com/invoice.pdf",
            },
        }
    ).encode()

    event = provider.parse_webhook_event(payload, None)

    assert event.type == "invoice.paid"
    assert event.org_id == "org_x"
    assert event.invoice is not None
    assert event.invoice.provider_invoice_id == "in_123"
    assert event.invoice.status == "paid"


def test_parse_webhook_event_without_invoice_data(provider: MockBillingProvider) -> None:
    payload = json.dumps({"type": "subscription.canceled", "org_id": "org_x"}).encode()
    event = provider.parse_webhook_event(payload, None)
    assert event.invoice is None


def test_parse_webhook_event_rejects_malformed_json(provider: MockBillingProvider) -> None:
    with pytest.raises(ApiError) as exc_info:
        provider.parse_webhook_event(b"not json", None)
    assert exc_info.value.status_code == 400


@pytest.mark.parametrize("body", [{"org_id": "org_x"}, {"type": "invoice.paid"}])
def test_parse_webhook_event_rejects_missing_type_or_org_id(provider: MockBillingProvider, body: dict) -> None:
    with pytest.raises(ApiError) as exc_info:
        provider.parse_webhook_event(json.dumps(body).encode(), None)
    assert exc_info.value.status_code == 400
