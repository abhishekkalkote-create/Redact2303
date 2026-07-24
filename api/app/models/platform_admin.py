from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PlatformAdmin(Base, TimestampMixin):
    """Platform-scope, not a membership. Never grants tenant content access on its own
    (see specs/08-security-compliance.md § Support access model)."""

    __tablename__ = "platform_admins"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    permissions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
