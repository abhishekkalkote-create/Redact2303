from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin

MANUAL_EXTRACTION_STATUSES = ("pending", "processing", "completed", "failed")
DRAFT_RULE_STATUSES = ("pending", "accepted", "rejected")


class Manual(Base, TimestampMixin):
    """specs/06 § Manual-to-rule extraction: "Upload manual/exemption guide/SOP (PDF) →
    extraction job." One extraction attempt per manual (re-upload to retry) — the job's
    own state lives on this row rather than a separate rule_extraction_jobs table, same
    simplification Phase 1 used before dedicated pipeline workers existed."""

    __tablename__ = "manuals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("mnl"))
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    s3_key: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    extraction_status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(String, nullable=True)


class DraftRule(Base, TimestampMixin):
    """Extraction output awaiting human accept/edit/reject — fields mirror Rule plus
    `ai_notes` (ambiguity notes) and `source_ref` (section anchor + quoted text,
    specs/06's "source_ref (section anchor + quoted text)")."""

    __tablename__ = "draft_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("drft"))
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    manual_id: Mapped[str] = mapped_column(
        String, ForeignKey("manuals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_key: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    exemption_code_id: Mapped[str | None] = mapped_column(String, ForeignKey("exemption_codes.id"), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    confidence_policy: Mapped[str] = mapped_column(String, nullable=False, default="suggest")
    exclusions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    scope: Mapped[str] = mapped_column(String, nullable=False, default="org")
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_notes: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
