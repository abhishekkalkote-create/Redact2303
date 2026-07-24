"""specs/04-api-spec.md "Webhooks (org-configurable)": document.ready_for_review and
document.exported for Phase 3 (export.integrity_failed and usage.threshold_* land later,
once Phase 5's metering/plan-allowance tracking exists to actually fire them from).

webhook_subscriptions: org-configurable delivery targets, HMAC secret encrypted at rest
via app/crypto/envelope.py (same treatment as redaction_candidates.display_text — it's
effectively an API credential). webhook_deliveries: one row per delivery attempt, mutable
(status/attempt_count/next_retry_at update as retries happen) — NOT append-only like
audit_events, since retry bookkeeping requires updates.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
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
        "webhook_subscriptions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String, nullable=False),
        sa.Column("secret_encrypted", sa.String, nullable=False),
        sa.Column("events", sa.JSON, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="active"),
        sa.Column("created_by", sa.String, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status in ('active','disabled')", name="ck_webhook_subscriptions_status"),
    )
    op.create_index("ix_webhook_subscriptions_org_id", "webhook_subscriptions", ["org_id"])
    _rls("webhook_subscriptions")

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "subscription_id", sa.String,
            sa.ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("event", sa.String, nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("response_status", sa.Integer, nullable=True),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status in ('pending','success','failed','dead')", name="ck_webhook_deliveries_status"
        ),
    )
    op.create_index("ix_webhook_deliveries_org_id", "webhook_deliveries", ["org_id"])
    op.create_index("ix_webhook_deliveries_subscription_id", "webhook_deliveries", ["subscription_id"])
    op.create_index(
        "ix_webhook_deliveries_retry_pending", "webhook_deliveries", ["status", "next_retry_at"],
        postgresql_where=sa.text("status = 'failed'"),
    )
    _rls("webhook_deliveries")


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_subscriptions")
