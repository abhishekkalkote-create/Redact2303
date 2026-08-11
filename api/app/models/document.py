from datetime import datetime

from sqlalchemy import ARRAY, JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin

# specs/03-data-model.md state machine:
DOCUMENT_STATUSES = (
    "uploaded", "scanning", "queued", "extracting", "detecting", "ready_for_review",
    "in_review", "review_complete", "awaiting_approval", "approved", "exported",
    "error", "deleted",
)
DOCUMENT_SOURCES = ("upload", "email", "batch")


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("doc"))
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("requests.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False, default="upload")
    status: Mapped[str] = mapped_column(String, nullable=False, default="uploaded")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ocr_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rule_set_version_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    s3_key_original: Mapped[str | None] = mapped_column(String, nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # specs/08-security-compliance.md: "Legal-hold flag per document/request suspends
    # deletion." Read by Phase 5's retention-sweep cron handler; not yet enforced anywhere.
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DocumentPage(Base, TimestampMixin):
    __tablename__ = "document_pages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("pg"))
    doc_id: Mapped[str] = mapped_column(
        String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    s3_key_preview: Mapped[str | None] = mapped_column(String, nullable=True)
    width: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    height: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    rotation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ocr_confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    has_text_layer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
