"""Public redaction-certificate verification (specs/05-redaction-pipeline.md Stage 6.5:
"verification endpoint public"). Same RLS pattern as migration 0001's
`invite_token_lookup`: a session that declares (via set_config) the EXACT artifact id it's
asking about may see only that one row — never a listing. Export artifact ids are 128-bit
ULIDs, so this can't be used to enumerate other orgs' exports; it only exposes a row to
someone who already has that row's id (e.g. from a certificate they were handed).

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE POLICY public_certificate_lookup ON export_artifacts "
        "FOR SELECT USING (id = current_setting('app.lookup_export_artifact_id', true))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY public_certificate_lookup ON export_artifacts")
