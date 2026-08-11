from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin

# specs/08-security-compliance.md § Support access model: "customer Agency Admin approves
# a scoped, time-bound (<= 24h) grant." No "expired" stored status — nothing transitions
# a row into it (there's no cron for it, and no platform-admin content endpoint consumes
# an active grant yet — see app/routers/platform.py's module docstring); an approved grant
# past its expires_at is simply no longer active, computed at read time
# (app/schemas/platform.py's SupportGrantOut.is_active), not stored as a separate state.
GRANT_STATUSES = ("requested", "approved", "denied", "revoked")


class SupportGrant(Base, TimestampMixin):
    """Ordinary tenant table (standard org_id RLS) despite being requested by a platform
    admin who has no membership in the org — app/services/support_grant_service.py's
    request_grant() writes it via a plain org_session(org_id), same as any other
    org-scoped write; no cross-tenant RLS exemption needed here (unlike listing which
    orgs exist at all — see migration 0011)."""

    __tablename__ = "support_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("spgrt"))
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="requested")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
