"""Phase 5 slice 2 (the cron primitive): a cron handler that sweeps every org — starting
with webhook-retry today, usage-aggregate and retention-sweep later — has to discover
which orgs exist before it can loop `org_session(org_id)` over each one. There is
currently no RLS-safe way to do that. `organizations`' only policy (migration 0001) is
`id = current_setting('app.org_id', true)`; with no org context set at all, that's
`id = NULL`, never true, so a plain no-context session sees zero rows — even for the orgs
directory itself.

Adds a second, narrowly-scoped PERMISSIVE policy (Postgres OR's multiple permissive
policies for the same command together) granting SELECT-only visibility into
`organizations` when `app.system_context` is set — a session variable ONLY ever set by
app/db/session.py's `system_session()`, never derived from client input, and never used
for anything but this one directory lookup. This widens visibility into the org
*directory* only; every content-bearing tenant table keeps its existing strict
tenant_isolation policy untouched, and every actual per-org read/write in a cron handler
still goes through the normal org-scoped `org_session(org_id)` with full RLS enforced.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE POLICY system_context_select ON organizations "
        "FOR SELECT "
        "USING (current_setting('app.system_context', true) = 'true')"
    )


def downgrade() -> None:
    op.execute("DROP POLICY system_context_select ON organizations")
