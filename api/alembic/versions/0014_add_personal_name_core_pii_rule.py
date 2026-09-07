"""Adds CPII-10 "Personal name" (entity_type PERSON, unconditional - no context_words)
to the existing global rsv_core_pii_v1 rule_set_version.

Found missing entirely 2026-09-07: every other PERSON-entity rule in
app/seed/starter_rule_packs.py (PS-1, PS-3, HR-1, HR-4) is context-gated to a specific
sensitive scenario (victim/witness, juvenile, medical leave, beneficiary). There was no
unconditional "this is a person's name" rule anywhere in Core PII, so a document with a
plain name and no such context word nearby flagged email/phone but never the name, even
though Presidio's SpacyRecognizer detects PERSON entities unconditionally - nothing in
the rule set had a trigger that would match it.

Inserted directly into the existing published rsv_core_pii_v1 row (the same
system-seed-data bypass migration 0008 itself used to populate it in the first place) -
the app-level "you can't add a rule directly to a global starter published version"
guard is an API constraint on user actions, not a schema constraint, and doesn't apply
to platform seed migrations. Orgs that already cloned Core PII into an org-owned draft
before this migration runs won't retroactively get this rule (seed data never overwrites
a user's own clone, same as any other seed-data update) - they'd need to re-clone or add
the equivalent rule to their own draft manually.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RULE_ID = "rul_cpii_10"


def upgrade() -> None:
    # ON CONFLICT DO NOTHING, not a plain insert: app/seed/starter_rule_packs.py's
    # get_rules() is a live, shared function that migration 0008 itself imports and
    # calls - editing that file to add this rule (as this change does) means a FRESH
    # database running 0008 from scratch already inserts this exact row, and a plain
    # insert here would then hit a duplicate-key error on that path. This migration only
    # needs to actually do anything for a database that ran the OLD 0008 before this
    # rule existed in get_rules() at all.
    op.execute(
        sa.text(
            """
            INSERT INTO rules (
                id, rule_set_version_id, org_id, rule_key, name, trigger_type, config,
                exemption_code_id, exemption_library_code, priority, confidence_policy,
                exclusions, scope, source_ref, status
            ) VALUES (
                :id, 'rsv_core_pii_v1', NULL, 'CPII-10', 'Personal name', 'entity',
                '{"entity_type": "PERSON"}', NULL, 'b(6)', 100, 'suggest', '[]', 'org', NULL, 'active'
            )
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(id=_RULE_ID)
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM rules WHERE id = :id").bindparams(id=_RULE_ID))
