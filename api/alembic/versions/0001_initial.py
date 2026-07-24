"""initial: organizations, users, memberships, invites, platform_admins + RLS

Revision ID: 0001
Revises:
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("slug", sa.String, nullable=False, unique=True),
        sa.Column("jurisdiction_state", sa.String(3), nullable=False),
        sa.Column("org_type", sa.String, nullable=False),
        sa.Column("plan", sa.String, nullable=False, server_default="pilot"),
        sa.Column("plan_status", sa.String, nullable=False, server_default="trialing"),
        sa.Column("settings", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("kms_key_arn", sa.String, nullable=True),
        sa.Column("stripe_customer_id", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "org_type in ('police','city_clerk','county','state','school','other')",
            name="ck_organizations_org_type",
        ),
        sa.CheckConstraint(
            "plan in ('pilot','starter','growth','enterprise')", name="ck_organizations_plan"
        ),
        sa.CheckConstraint(
            "plan_status in ('trialing','active','past_due','suspended','canceled')",
            name="ck_organizations_plan_status",
        ),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("cognito_sub", sa.String, nullable=True, unique=True),
        sa.Column("email", sa.String, nullable=False, unique=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="active"),
        sa.Column("mfa_enrolled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status in ('active','disabled')", name="ck_users_status"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "memberships",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column(
            "org_id", sa.String,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="active"),
        sa.Column("invited_by", sa.String, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),
        sa.CheckConstraint(
            "role in ('reviewer','supervisor','agency_admin','billing_admin')",
            name="ck_memberships_role",
        ),
        sa.CheckConstraint(
            "status in ('invited','active','deactivated')", name="ck_memberships_status"
        ),
    )
    op.create_index("ix_memberships_org_id", "memberships", ["org_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "invites",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column(
            "org_id", sa.String,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("email", sa.String, nullable=False),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("token_hash", sa.String, nullable=False, unique=True),
        sa.Column("invited_by", sa.String, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_invites_org_id", "invites", ["org_id"])

    op.create_table(
        "platform_admins",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permissions", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --- Row-Level Security (CLAUDE.md invariant #1; specs/08-security-compliance.md) ---
    # `organizations` has no org_id column — a row's tenant IS its own id.
    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON organizations "
        "USING (id = current_setting('app.org_id', true))"
    )

    for table in ("memberships", "invites"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (org_id = current_setting('app.org_id', true))"
        )
    # `users` and `platform_admins` are intentionally NOT org-scoped (global identity /
    # platform scope) — no org_id column, so the CI "every org_id table has a policy"
    # check does not apply to them.

    # Second, permissive policy on `memberships`: a session that has authenticated as user X
    # (declared via set_config('app.user_id', X, true), never client-supplied) may see ITS OWN
    # membership rows across every org, not just whichever org happens to be in app.org_id.
    # This is load-bearing, not an extra: without it there is no RLS-safe way to even
    # discover which org(s) a user belongs to (the chicken-and-egg of tenant_isolation
    # above — you can't set app.org_id to the right value before you know it), and no way
    # to enforce "one active org per user" (specs/03-data-model.md) across orgs the caller
    # isn't currently scoped to. Permissive policies OR together, so this only ever widens
    # visibility to the caller's own rows — it never narrows tenant_isolation's guarantees
    # for anyone else's rows.
    op.execute(
        "CREATE POLICY self_membership_lookup ON memberships "
        "FOR SELECT USING (user_id = current_setting('app.user_id', true))"
    )

    # Same shape on `invites`: a session that declares (via set_config) the exact token_hash
    # it's asserting knowledge of may see only the one row matching that hash — never a
    # listing. Only someone holding the original 256-bit token can compute the matching hash,
    # so this can't be used to enumerate other orgs' invites.
    op.execute(
        "CREATE POLICY invite_token_lookup ON invites "
        "FOR SELECT USING (token_hash = current_setting('app.lookup_invite_token_hash', true))"
    )


def downgrade() -> None:
    op.drop_table("platform_admins")
    op.drop_table("invites")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("organizations")
