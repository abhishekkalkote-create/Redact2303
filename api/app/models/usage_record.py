from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin

METRICS = ("pages_processed", "ocr_pages", "llm_pages", "documents", "exports", "seats_active")


class UsageRecord(Base, TimestampMixin):
    """specs/09-admin-billing.md — emitted at processing completion; idempotent by
    (job_id, metric) so a retried job never double-counts (see the unique constraint)."""

    __tablename__ = "usage_records"
    __table_args__ = (UniqueConstraint("job_id", "metric", name="uq_usage_job_metric"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("use"))
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_id: Mapped[str | None] = mapped_column(String, ForeignKey("documents.id"), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String, ForeignKey("processing_jobs.id"), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    billing_period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    reported_to_billing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
