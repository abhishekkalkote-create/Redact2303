"""specs/06-exemption-taxonomy.md § Rule engine / specs/03-data-model.md:
"organizations 1─* rule_packs 1─* rule_set_versions 1─* rules" and
"manuals 1─* rule_extraction_jobs ─* draft_rules" (the extraction job's state is folded
into `manuals.extraction_status` for v1 — one extraction attempt per manual, re-upload to
retry — same simplification Phase 1 used for pipeline jobs before a dedicated worker
existed).

`rule_packs.org_id` is nullable — NULL means a global starter pack (specs/06: "Starter
packs (shipped, global, cloneable)"), a single row visible to every org. This is a
genuinely different shape from exemption_library/exemption_codes (which split global vs
org-owned into two separate tables) because rule_packs/rule_set_versions/rules need to
carry an org's OWN clone-and-customize history in the same table shape as the starter
packs it was cloned from — so RLS here is asymmetric: any row can be SELECTed if it's
global (org_id IS NULL) or belongs to your org; only your-org rows can be
INSERTed/UPDATEd (nobody can write a global row through the ORM — only migrations/seed
do). `rule_set_versions`/`rules` denormalize `org_id` from their parent (spec's own
minimal column list omits it) purely so this same RLS pattern can be a plain column
check instead of a correlated subquery through rule_packs — the same denormalization
this codebase already does everywhere else (redaction_candidates.org_id, etc.).

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _global_or_own_rls(table: str) -> None:
    """USING allows reading a global row (org_id IS NULL) from any session, or your own
    org's row. WITH CHECK uses IS NOT DISTINCT FROM (NULL-safe equality) rather than `=`
    so a connection with NO org context set (a migration, or the startup seed script —
    both run with app.org_id unset, i.e. current_setting returns NULL) can insert the
    global starter-pack rows; a normal app request always has app.org_id set to a real
    org, so `org_id = NULL` for it correctly still fails — a tenant can never write a
    global row, only its own."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING (org_id IS NULL OR org_id = current_setting('app.org_id', true)) "
        f"WITH CHECK (org_id IS NOT DISTINCT FROM current_setting('app.org_id', true))"
    )


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING (org_id = current_setting('app.org_id', true)) "
        f"WITH CHECK (org_id = current_setting('app.org_id', true))"
    )


def upgrade() -> None:
    op.create_table(
        "rule_packs",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("description", sa.String, nullable=True),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="active"),
        sa.Column("cloned_from_pack_id", sa.String, sa.ForeignKey("rule_packs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "category in ('core_pii','public_safety','hr','legal','health','custom')",
            name="ck_rule_packs_category",
        ),
        sa.CheckConstraint("status in ('active','archived')", name="ck_rule_packs_status"),
    )
    op.create_index("ix_rule_packs_org_id", "rule_packs", ["org_id"])
    _global_or_own_rls("rule_packs")

    op.create_table(
        "rule_set_versions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("rule_pack_id", sa.String, sa.ForeignKey("rule_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="draft"),
        sa.Column("published_by", sa.String, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("changelog", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status in ('draft','published','archived')", name="ck_rule_set_versions_status"),
        sa.UniqueConstraint("rule_pack_id", "version", name="uq_rule_set_versions_pack_version"),
    )
    op.create_index("ix_rule_set_versions_org_id", "rule_set_versions", ["org_id"])
    op.create_index("ix_rule_set_versions_rule_pack_id", "rule_set_versions", ["rule_pack_id"])
    _global_or_own_rls("rule_set_versions")

    op.create_table(
        "rules",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column(
            "rule_set_version_id", sa.String,
            sa.ForeignKey("rule_set_versions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("rule_key", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("trigger_type", sa.String, nullable=False),
        sa.Column("config", sa.JSON, nullable=False),
        # exemption_code_id: a specific org's cloned code (org-owned rules can point
        # directly at one). exemption_library_code: a global library code string (e.g.
        # "b(6)") resolved to the executing org's own clone at run time — how starter-pack
        # rules stay org-agnostic (same resolution app/pipeline/detect.py already does for
        # the hardcoded Core PII pack; see app/services/exemption_service.py).
        sa.Column("exemption_code_id", sa.String, sa.ForeignKey("exemption_codes.id"), nullable=True),
        sa.Column("exemption_library_code", sa.String, nullable=True),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("confidence_policy", sa.String, nullable=False, server_default="suggest"),
        sa.Column("exclusions", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("scope", sa.String, nullable=False, server_default="org"),
        sa.Column("source_ref", sa.String, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "trigger_type in ('regex','dictionary','entity','metadata','llm_context')",
            name="ck_rules_trigger_type",
        ),
        sa.CheckConstraint(
            "confidence_policy in ('auto_high','suggest','flag_low')", name="ck_rules_confidence_policy"
        ),
        sa.CheckConstraint("scope in ('org','document_type','request')", name="ck_rules_scope"),
        sa.CheckConstraint("status in ('active','disabled')", name="ck_rules_status"),
    )
    op.create_index("ix_rules_org_id", "rules", ["org_id"])
    op.create_index("ix_rules_rule_set_version_id", "rules", ["rule_set_version_id"])
    _global_or_own_rls("rules")

    op.create_table(
        "manuals",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String, nullable=False),
        sa.Column("s3_key", sa.String, nullable=False),
        sa.Column("uploaded_by", sa.String, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("extraction_status", sa.String, nullable=False, server_default="pending"),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "extraction_status in ('pending','processing','completed','failed')",
            name="ck_manuals_extraction_status",
        ),
    )
    op.create_index("ix_manuals_org_id", "manuals", ["org_id"])
    _rls("manuals")

    op.create_table(
        "draft_rules",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("manual_id", sa.String, sa.ForeignKey("manuals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_key", sa.String, nullable=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("trigger_type", sa.String, nullable=False),
        sa.Column("config", sa.JSON, nullable=False),
        sa.Column("exemption_code_id", sa.String, sa.ForeignKey("exemption_codes.id"), nullable=True),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("confidence_policy", sa.String, nullable=False, server_default="suggest"),
        sa.Column("exclusions", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("scope", sa.String, nullable=False, server_default="org"),
        sa.Column("source_ref", sa.String, nullable=True),
        sa.Column("ai_notes", sa.String, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "trigger_type in ('regex','dictionary','entity','metadata','llm_context')",
            name="ck_draft_rules_trigger_type",
        ),
        sa.CheckConstraint("status in ('pending','accepted','rejected')", name="ck_draft_rules_status"),
    )
    op.create_index("ix_draft_rules_org_id", "draft_rules", ["org_id"])
    op.create_index("ix_draft_rules_manual_id", "draft_rules", ["manual_id"])
    _rls("draft_rules")


def downgrade() -> None:
    op.drop_table("draft_rules")
    op.drop_table("manuals")
    op.drop_table("rules")
    op.drop_table("rule_set_versions")
    op.drop_table("rule_packs")
