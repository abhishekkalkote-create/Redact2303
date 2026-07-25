"""Fixes a latent bug found while testing Phase 4's rule-engine wiring (not introduced by
it — exposed by it, since it's the first time a deterministic and an LLM candidate ever
overlapped in an exercised test, forcing app.pipeline.merge to actually delete a
redaction_candidates row).

Postgres's FK enforcement, when deleting a row from the REFERENCED side of a foreign key
(here: redaction_candidates), runs an internal `SELECT ... FOR KEY SHARE` against the
REFERENCING table (review_actions) to check for dependent rows — and that locking read
requires UPDATE-equivalent privilege on the referencing table, not just SELECT. Migration
0002's `_append_only()` REVOKE UPDATE, DELETE ON review_actions therefore silently broke
the FK check itself: ANY delete of a redaction_candidates row now fails with "permission
denied for table review_actions", regardless of whether any review_actions row actually
references it. Verified empirically (not assumed) — see project memory on the general
REVOKE-affects-even-the-owner behavior this compounds with.

Fix: drop the FK entirely — review_actions.candidate_id stays as a plain nullable
column. This matches audit_events' own already-stated design intent exactly
("org deletion never deletes audit rows" — audit_events was deliberately built with NO
FK at all, for this same "outlive the row it describes" reason). A review action
describing what a human did to a candidate should survive that candidate later being
merged away or deleted, not disappear or block the deletion.

Known follow-up, NOT fixed here (out of scope for this change, flagging rather than
silently leaving it): review_actions.doc_id/org_id and export_artifacts.doc_id/org_id
are still ON DELETE CASCADE, which will hit this exact same FOR KEY SHARE privilege
problem the moment anything hard-deletes an organization or document row (no code path
does that yet — Phase 5/6's data retention jobs and org offboarding will). Per
audit_events' own precedent, these probably shouldn't cascade-delete at all.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("review_actions_candidate_id_fkey", "review_actions", type_="foreignkey")


def downgrade() -> None:
    op.create_foreign_key(
        "review_actions_candidate_id_fkey", "review_actions", "redaction_candidates", ["candidate_id"], ["id"]
    )
