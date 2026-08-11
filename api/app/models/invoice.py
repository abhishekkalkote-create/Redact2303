from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin

# specs/09-admin-billing.md: "Stripe is display-truth for invoices, our DB is truth for
# usage." This table only mirrors Stripe's invoice state for the org-facing Usage &
# Billing screen (specs/07-ui-spec.md § 8) — never the source of truth for what's owed.
INVOICE_STATUSES = ("draft", "open", "paid", "uncollectible", "void")


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("stripe_invoice_id", name="uq_invoices_stripe_invoice_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("invc"))
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable: null until the billing provider actually issues the invoice; unique once
    # set, so the Stripe webhook handler can upsert idempotently on this column.
    stripe_invoice_id: Mapped[str | None] = mapped_column(String, nullable=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM, matches usage_records.billing_period
    line_items: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    pdf_url: Mapped[str | None] = mapped_column(String, nullable=True)
