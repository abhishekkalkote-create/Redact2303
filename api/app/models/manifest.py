from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin

CURRENT_SCHEMA_VERSION = 1


class Manifest(Base, TimestampMixin):
    """specs/02-architecture.md ADR-6: single source of truth for review state. One row
    per document; `version` bumps on any change (candidates, completeness) — see
    specs/04-api-spec.md's If-Match usage on PATCH /candidates/{id}."""

    __tablename__ = "manifests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("man"))
    doc_id: Mapped[str] = mapped_column(
        String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=CURRENT_SCHEMA_VERSION)
    snapshot_s3_key: Mapped[str | None] = mapped_column(String, nullable=True)
    completeness: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=lambda: {"pages_viewed": [], "low_conf_resolved": False}
    )
