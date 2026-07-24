from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin

USER_STATUSES = ("active", "disabled")


class User(Base, TimestampMixin):
    """Global identity. Not org-scoped — no RLS (see specs/03-data-model.md).

    `cognito_sub` is nullable only to accommodate the local dev-auth provider before a
    Cognito user pool exists (specs/02-architecture.md ADR-7); every prod user has one.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("usr"))
    cognito_sub: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    mfa_enrolled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
