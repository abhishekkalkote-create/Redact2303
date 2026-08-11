"""specs/02-architecture.md ADR-8: "Stripe behind a billing abstraction ... so a
gov-focused biller could replace Stripe without touching product code." Same
provider-seam pattern as app/llm/provider.py: a real StripeProvider for prod (added once
test-mode credentials exist), MockBillingProvider (app/billing/mock_provider.py) for
local dev/tests until then — selected by settings, see get_billing_provider() below.

Every caller (app/services/billing_service.py) talks to this Protocol only, never a
vendor SDK or vendor event shape directly — parse_webhook_event normalizes whatever the
underlying provider's webhook payload looks like into BillingEvent before anything else
in the app ever sees it.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.core.config import Settings, get_settings


@dataclass
class CheckoutSession:
    id: str
    url: str


@dataclass
class BillingInvoice:
    """Mirrors just enough of a provider invoice to populate app/models/invoice.py —
    that table is display-truth only (specs/09-admin-billing.md: "Stripe is
    display-truth for invoices")."""

    provider_invoice_id: str
    period: str  # YYYY-MM
    status: str
    line_items: list[dict] = field(default_factory=list)
    pdf_url: str | None = None


@dataclass
class BillingEvent:
    """Normalized shape every provider's own webhook payload gets translated into —
    `type` is OUR vocabulary, not the vendor's. Drives the plan_status state machine in
    app/services/billing_service.py."""

    type: str  # "checkout.completed" | "invoice.paid" | "invoice.payment_failed" | "subscription.canceled"
    org_id: str
    plan: str | None = None
    invoice: BillingInvoice | None = None


class BillingProvider(ABC):
    @abstractmethod
    async def create_customer(self, org_id: str, org_name: str, email: str) -> str:
        """Returns the provider's customer id — stored on Organization.stripe_customer_id
        regardless of the actual provider (the ADR-8 abstraction means it isn't
        necessarily Stripe's)."""
        ...

    @abstractmethod
    async def create_checkout_session(
        self, org_id: str, customer_id: str, plan: str, success_url: str, cancel_url: str
    ) -> CheckoutSession: ...

    @abstractmethod
    async def create_portal_session(self, customer_id: str, return_url: str) -> str:
        """Returns a portal URL (Stripe: the Billing Portal)."""
        ...

    @abstractmethod
    def parse_webhook_event(self, payload: bytes, signature_header: str | None) -> BillingEvent:
        """Verifies the signature (real providers) and normalizes the vendor event.
        Raises ApiError(400) on a malformed or unverifiable payload."""
        ...


def get_billing_provider(settings: Settings | None = None) -> BillingProvider:
    settings = settings or get_settings()
    if settings.env == "local" and not settings.stripe_enabled:
        from app.billing.mock_provider import MockBillingProvider

        return MockBillingProvider()
    raise NotImplementedError(
        "stripe_enabled is set but no real StripeProvider exists yet — wire the Stripe "
        "SDK behind BillingProvider before flipping this flag."
    )
