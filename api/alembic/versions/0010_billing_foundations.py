"""Phase 5 slice 1: data model only, nothing reads or writes any of this yet.

invoices: specs/09-admin-billing.md "Stripe is display-truth for invoices" — this table
mirrors Stripe's invoice state for the org-facing Usage & Billing screen
(specs/07-ui-spec.md § 8); RLS-isolated like every other tenant table.

documents.legal_hold / requests.legal_hold: specs/08-security-compliance.md "Legal-hold
flag per document/request suspends deletion" — read by the retention-sweep cron handler
that lands later in Phase 5.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
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
        "invoices",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stripe_invoice_id", sa.String, nullable=True),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("line_items", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("status", sa.String, nullable=False, server_default="draft"),
        sa.Column("pdf_url", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status in ('draft','open','paid','uncollectible','void')", name="ck_invoices_status"
        ),
        sa.UniqueConstraint("stripe_invoice_id", name="uq_invoices_stripe_invoice_id"),
    )
    op.create_index("ix_invoices_org_id", "invoices", ["org_id"])
    _rls("invoices")

    op.add_column("documents", sa.Column("legal_hold", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("requests", sa.Column("legal_hold", sa.Boolean, nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("requests", "legal_hold")
    op.drop_column("documents", "legal_hold")
    op.drop_table("invoices")
