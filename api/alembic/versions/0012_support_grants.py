"""Phase 5 slice 6: specs/08-security-compliance.md § Support access model — "customer
Agency Admin approves a scoped, time-bound (<= 24h) grant; every access during grant
writes customer-visible audit events; grants listed in the org's audit UI." Ordinary
tenant table (standard org_id RLS, same _rls() helper as prior migrations) — a platform
admin requesting a grant has no membership in the org, so
app/services/support_grant_service.py writes this via a plain org_session(org_id)
rather than needing any RLS exemption (unlike migration 0011's org-directory lookup).

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
        "support_grants",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by", sa.String, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="requested"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.String, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status in ('requested','approved','denied','revoked')", name="ck_support_grants_status"),
    )
    op.create_index("ix_support_grants_org_id", "support_grants", ["org_id"])
    _rls("support_grants")


def downgrade() -> None:
    op.drop_table("support_grants")
