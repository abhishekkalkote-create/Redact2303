from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin

SUBSCRIPTION_STATUSES = ("active", "disabled")
DELIVERY_STATUSES = ("pending", "success", "failed", "dead")

# specs/04-api-spec.md: Phase 3 fires these two; export.integrity_failed and
# usage.threshold_80/95 are specced but wait on Phase 5's metering/plan-allowance work.
SUPPORTED_EVENTS = ("document.ready_for_review", "document.exported")


class WebhookSubscription(Base, TimestampMixin):
    """Org-configurable delivery target (specs/04-api-spec.md § Webhooks). `secret`
    never persists in plaintext — encrypted the same way as redaction_candidates'
    display_text (app/crypto/envelope.py); it's effectively an API credential."""

    __tablename__ = "webhook_subscriptions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("whsub"))
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String, nullable=False)
    secret_encrypted: Mapped[str] = mapped_column(String, nullable=False)
    events: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)


class WebhookDelivery(Base, TimestampMixin):
    """One row per delivery attempt. Mutable (unlike audit_events) — attempt_count and
    next_retry_at update in place as retries happen."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("whdlv"))
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subscription_id: Mapped[str] = mapped_column(
        String, ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
