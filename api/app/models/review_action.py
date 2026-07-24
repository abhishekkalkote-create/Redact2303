from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin

ACTIONS = (
    "approve", "reject", "modify", "create", "bulk_approve", "complete_review",
    "approve_doc", "return_doc", "reopen",
)


class ReviewAction(Base, TimestampMixin):
    """Append-only (specs/03-data-model.md) — no UPDATE/DELETE, enforced at the DB level
    like audit_events (see migration 0002's REVOKE)."""

    __tablename__ = "review_actions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("ract"))
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doc_id: Mapped[str] = mapped_column(
        String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("redaction_candidates.id"), nullable=True
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
