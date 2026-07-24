from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin

ORG_TYPES = ("police", "city_clerk", "county", "state", "school", "other")
PLANS = ("pilot", "starter", "growth", "enterprise")
PLAN_STATUSES = ("trialing", "active", "past_due", "suspended", "canceled")

DEFAULT_SETTINGS = {
    "dual_approval_required": False,
    "default_rule_pack_ids": [],
    "retention_days_uploads": 90,
    "retention_days_exports": 2555,  # 7 years
    "features": {},
    "export_defaults": {"clean_pdf": True, "annotated_pdf": False, "exemption_log": True},
}


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("org"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    jurisdiction_state: Mapped[str] = mapped_column(String(3), nullable=False)  # 2-letter or 'FED'
    org_type: Mapped[str] = mapped_column(String, nullable=False)
    plan: Mapped[str] = mapped_column(String, nullable=False, default="pilot")
    plan_status: Mapped[str] = mapped_column(String, nullable=False, default="trialing")
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    kms_key_arn: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
