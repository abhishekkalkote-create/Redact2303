"""specs/01-product-spec.md US-10: "As a Supervisor, I get an escalation queue of items
reviewers flagged" / specs/07-ui-spec.md screen 3 review workspace: "[Approve] [Reject]
[Escalate]" — a third, independent action alongside approve/reject, not a
redaction_candidates.state value (state stays suggested/approved/rejected per
specs/03-data-model.md's existing state machine). Escalation is tracked as its own
nullable timestamp/note/actor on the candidate, and as new review_actions kinds.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("redaction_candidates", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("redaction_candidates", sa.Column("escalated_by", sa.String, sa.ForeignKey("users.id"), nullable=True))
    op.add_column("redaction_candidates", sa.Column("escalated_note", sa.String, nullable=True))
    op.create_index(
        "ix_redaction_candidates_escalated_at", "redaction_candidates", ["escalated_at"],
        postgresql_where=sa.text("escalated_at IS NOT NULL"),
    )

    op.drop_constraint("ck_review_actions_action", "review_actions", type_="check")
    op.create_check_constraint(
        "ck_review_actions_action",
        "review_actions",
        "action in ('approve','reject','modify','create','bulk_approve','complete_review',"
        "'approve_doc','return_doc','reopen','escalate','resolve_escalation')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_review_actions_action", "review_actions", type_="check")
    op.create_check_constraint(
        "ck_review_actions_action",
        "review_actions",
        "action in ('approve','reject','modify','create','bulk_approve','complete_review',"
        "'approve_doc','return_doc','reopen')",
    )

    op.drop_index("ix_redaction_candidates_escalated_at", table_name="redaction_candidates")
    op.drop_column("redaction_candidates", "escalated_note")
    op.drop_column("redaction_candidates", "escalated_by")
    op.drop_column("redaction_candidates", "escalated_at")
