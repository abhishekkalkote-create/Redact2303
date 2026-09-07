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
from app.core.errors import ApiError
from app.core.ids import new_id


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

    @abstractmethod
    async def report_usage(self, customer_id: str, metric: str, quantity: int, period: str) -> None:
        """Reports a metered-usage quantity for a billing period (Stripe: meter events).
        Called by the usage-aggregate cron handler (app/routers/internal_cron.py); our own
        usage_records stay the truth for what happened, this is just telling the biller."""
        ...


class DisabledBillingProvider(BillingProvider):
    """Stripe isn't configured (stripe_enabled=false) - used in ANY environment where
    that's true, not just local (get_billing_provider() below used to unconditionally
    raise for env != "local" regardless of stripe_enabled, which crashed org creation
    entirely - every org creation calls create_customer(); specs/09-admin-billing.md
    already expects some orgs to pay by PO/ACH outside Stripe entirely, so billing not
    being wired yet must not block creating an org at all).

    Unlike MockBillingProvider (local-dev-and-tests-only: its parse_webhook_event trusts
    an UNSIGNED payload verbatim, which is only safe when nothing external can reach it),
    this provider's outbound methods no-op safely, but parse_webhook_event refuses
    instead of trusting unverified input - accepting a forged "invoice.paid" body from
    anyone would let them grant themselves billing state without paying anything, real
    or mock.
    """

    async def create_customer(self, org_id: str, org_name: str, email: str) -> str:
        return new_id("cus")  # placeholder id; no real billing yet, org creation still succeeds

    async def create_checkout_session(
        self, org_id: str, customer_id: str, plan: str, success_url: str, cancel_url: str
    ) -> CheckoutSession:
        raise ApiError(501, "Not Implemented", "Billing is not configured yet")

    async def create_portal_session(self, customer_id: str, return_url: str) -> str:
        raise ApiError(501, "Not Implemented", "Billing is not configured yet")

    def parse_webhook_event(self, payload: bytes, signature_header: str | None) -> BillingEvent:
        raise ApiError(501, "Not Implemented", "Billing webhooks are not configured yet")

    async def report_usage(self, customer_id: str, metric: str, quantity: int, period: str) -> None:
        return None  # nothing to report to; usage_records remains the source of truth either way


def get_billing_provider(settings: Settings | None = None) -> BillingProvider:
    settings = settings or get_settings()
    if not settings.stripe_enabled:
        if settings.env == "local":
            from app.billing.mock_provider import MockBillingProvider

            return MockBillingProvider()
        return DisabledBillingProvider()
    raise NotImplementedError(
        "stripe_enabled is set but no real StripeProvider exists yet — wire the Stripe "
        "SDK behind BillingProvider before flipping this flag."
    )
