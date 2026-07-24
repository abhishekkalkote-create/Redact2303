from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin

ROLES = ("reviewer", "supervisor", "agency_admin", "billing_admin")
MEMBERSHIP_STATUSES = ("invited", "active", "deactivated")


class Membership(Base, TimestampMixin):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("mem"))
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    invited_by: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
