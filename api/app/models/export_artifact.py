from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin

EXPORT_TYPES = (
    "clean_pdf", "annotated_pdf", "exemption_log_pdf", "exemption_log_csv",
    "exemption_log_json", "certificate_pdf",
)


class ExportArtifact(Base, TimestampMixin):
    """Immutable (specs/03-data-model.md) — no UPDATE/DELETE once written."""

    __tablename__ = "export_artifacts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("exp"))
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doc_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    request_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("requests.id", ondelete="CASCADE"), nullable=True
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    s3_key: Mapped[str] = mapped_column(String, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    manifest_version: Mapped[int] = mapped_column(Integer, nullable=False)
    integrity_check: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
