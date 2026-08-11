"""Phase 5 slice 10: specs/07-ui-spec.md § 1 onboarding — "optional sample document to
try instantly (demo doc processes free, exemplifies exemption citations)." Adds
'sample' as a valid documents.source value; app/pipeline/run.py's process_document
skips usage billing entirely for it (bill_usage=False), so it needs to be
distinguishable from a real upload/email/batch document.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_SOURCES = "'upload','email','batch'"
_NEW_SOURCES = "'upload','email','batch','sample'"


def upgrade() -> None:
    op.drop_constraint("ck_documents_source", "documents", type_="check")
    op.create_check_constraint("ck_documents_source", "documents", f"source in ({_NEW_SOURCES})")


def downgrade() -> None:
    op.drop_constraint("ck_documents_source", "documents", type_="check")
    op.create_check_constraint("ck_documents_source", "documents", f"source in ({_OLD_SOURCES})")
