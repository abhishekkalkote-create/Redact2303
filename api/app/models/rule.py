from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, TimestampMixin

RULE_PACK_CATEGORIES = ("core_pii", "public_safety", "hr", "legal", "health", "custom")
RULE_PACK_STATUSES = ("active", "archived")
RULE_SET_VERSION_STATUSES = ("draft", "published", "archived")
TRIGGER_TYPES = ("regex", "dictionary", "entity", "metadata", "llm_context")
CONFIDENCE_POLICIES = ("auto_high", "suggest", "flag_low")
RULE_SCOPES = ("org", "document_type", "request")
RULE_STATUSES = ("active", "disabled")


class RulePack(Base, TimestampMixin):
    """specs/06-exemption-taxonomy.md "Starter packs (shipped, global, cloneable)".
    `org_id IS NULL` means a global starter pack — see migration 0007's docstring for why
    RLS on this table (and rule_set_versions/rules below) is asymmetric."""

    __tablename__ = "rule_packs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("rpk"))
    org_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    cloned_from_pack_id: Mapped[str | None] = mapped_column(String, ForeignKey("rule_packs.id"), nullable=True)


class RuleSetVersion(Base, TimestampMixin):
    """specs/06: "Rule sets: draft → published (immutable) → archived." Publishing sets
    published_by/published_at and flips status; editing a published version means
    creating the NEXT draft version instead (enforced in app/services/rule_service.py,
    not just convention)."""

    __tablename__ = "rule_set_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("rsv"))
    rule_pack_id: Mapped[str] = mapped_column(
        String, ForeignKey("rule_packs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    published_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    changelog: Mapped[str | None] = mapped_column(String, nullable=True)


class Rule(Base, TimestampMixin):
    """specs/06 § Rule anatomy. `exemption_code_id` is a direct FK for org-owned rules
    that reference one of the org's own cloned codes; `exemption_library_code` is how
    global starter-pack rules stay org-agnostic — resolved to the executing org's clone
    at detection time (app/pipeline/rule_engine.py), the same resolution
    app/pipeline/detect.py already did for the hardcoded Core PII pack."""

    __tablename__ = "rules"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("rul"))
    rule_set_version_id: Mapped[str] = mapped_column(
        String, ForeignKey("rule_set_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    rule_key: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    exemption_code_id: Mapped[str | None] = mapped_column(String, ForeignKey("exemption_codes.id"), nullable=True)
    exemption_library_code: Mapped[str | None] = mapped_column(String, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    confidence_policy: Mapped[str] = mapped_column(String, nullable=False, default="suggest")
    exclusions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    scope: Mapped[str] = mapped_column(String, nullable=False, default="org")
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
