from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin


class Invite(Base, TimestampMixin):
    """Tokenized org invite. `token_hash` is SHA-256 of the token mailed to the invitee —
    the raw token is never persisted (see specs/04-api-spec.md POST /invites/{token}/accept)."""

    __tablename__ = "invites"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("inv"))
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    invited_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
