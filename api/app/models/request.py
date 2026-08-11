from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin

REQUEST_STATUSES = ("open", "in_review", "complete", "closed")


class RecordsRequest(Base, TimestampMixin):
    """A "Request" per specs/03-data-model.md — named RecordsRequest in code to avoid
    colliding with FastAPI/Starlette's own Request type."""

    __tablename__ = "requests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("req"))
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference_no: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    # specs/08-security-compliance.md: "Legal-hold flag per document/request suspends
    # deletion." Read by Phase 5's retention-sweep cron handler; not yet enforced anywhere.
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
