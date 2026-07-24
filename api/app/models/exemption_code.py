from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin

LEVELS = ("federal", "state")
STATUSES = ("active", "archived")


class ExemptionLibrary(Base, TimestampMixin):
    """Global federal/state reference catalog (specs/06-exemption-taxonomy.md levels 1-2).

    Deliberately NOT org-scoped and NOT RLS'd — like `users`/`platform_admins`, this is
    non-tenant reference data (public statute citations), so there's no isolation concern
    and no RLS-null-row edge case to design around. Orgs clone rows from here into their
    own `exemption_codes` (level 3, always org-scoped) to customize label/guidance.
    """

    __tablename__ = "exemption_library"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("exl"))
    code: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    statute_citation: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    guidance_url: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")


class ExemptionCode(Base, TimestampMixin):
    """Org taxonomy (level 3) — always org-scoped, RLS'd exactly like every other tenant
    table (no special-casing). `library_id` is set when cloned from the global library;
    null for org-only custom reason codes (e.g. "HR-1 employee home address")."""

    __tablename__ = "exemption_codes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("exc"))
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    library_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("exemption_library.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    statute_citation: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    guidance_url: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
