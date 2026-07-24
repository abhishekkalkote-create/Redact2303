from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin

ORIGINS = ("deterministic", "llm", "manual", "search_apply")
CONFIDENCES = ("high", "medium", "low", "n/a-manual")
STATES = ("suggested", "approved", "rejected", "modified")


class RedactionCandidate(Base, TimestampMixin):
    """specs/03-data-model.md. `display_text` holds application-layer ciphertext (envelope
    encryption, see app/crypto/envelope.py) — the most sensitive strings in the DB
    (specs/08-security-compliance.md § Encryption)."""

    __tablename__ = "redaction_candidates"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("cand"))
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doc_id: Mapped[str] = mapped_column(
        String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox: Mapped[dict] = mapped_column(JSON, nullable=False)
    text_span: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    display_text_encrypted: Mapped[str] = mapped_column(String, nullable=False)
    origin: Mapped[str] = mapped_column(String, nullable=False)
    source_rule_key: Mapped[str | None] = mapped_column(String, nullable=True)
    source_rule_version: Mapped[str | None] = mapped_column(String, nullable=True)
    recurrence_group_id: Mapped[str | None] = mapped_column(String, nullable=True)
    exemption_code_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("exemption_codes.id"), nullable=True
    )
    ai_justification: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False, default="suggested")
    detector_versions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # specs/01-product-spec.md US-10: a reviewer's "Escalate" action — independent of
    # `state`, which stays suggested/approved/rejected regardless of escalation.
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    escalated_note: Mapped[str | None] = mapped_column(String, nullable=True)
