"""specs/06-exemption-taxonomy.md § Starter packs (shipped, global, cloneable): Core
PII, Public Safety, HR/Personnel, Legal Privilege, Health. Each is one global
(org_id=NULL) rule_pack with one published rule_set_version (v1) containing real rules —
not placeholders. exemption_library_code always references a FEDERAL code (b(5)/b(6)/
7(A)/7(C)/7(D)/7(E)) because every org gets the federal library cloned regardless of
jurisdiction (specs/06: "get federal + their state library pre-cloned"); state-specific
codes are only ever a *preferred override* at detection time
(app/pipeline/detect.py's `_pick_exemption_code`), never the primary attachment for a
global rule that has to work for any org.

Core PII's entity list (SSN/credit card/bank/phone/email/DL/passport) matches what
app/pipeline/core_pii.py already hardcodes for Phase 1 — this promotes it to real schema
rows rather than duplicating it as a second, divergent implementation. The DOB and
home-address rules are new: core_pii.py's own docstring said adding them was "a
rules-engine change in Phase 4, not a code change" — this is that change.

`llm_context` rules (investigative techniques, employee discipline, legal analysis
without an explicit marker) are seeded here as real rows the schema can hold, but are not
executed by anything yet — that wiring is app/pipeline/detect_llm.py's contextual pass,
a separate piece of work.

confidence_policy is 'suggest' for every seed rule, never 'auto_high' — preserves the
existing invariant (specs/05: "Deterministic-only findings are never auto-approved")
that pre-dates confidence_policy existing as a per-rule field at all.

Row data lives in app/seed/starter_rule_packs.py (shared with tests/conftest.py, which
has to re-seed these after a TRUNCATE-based test cleanup wipes the whole table — see
that module's docstring) rather than being duplicated inline here.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.seed.starter_rule_packs import get_packs, get_rules, get_versions

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pack_table = sa.table(
        "rule_packs",
        sa.column("id", sa.String), sa.column("org_id", sa.String), sa.column("name", sa.String),
        sa.column("description", sa.String), sa.column("category", sa.String), sa.column("status", sa.String),
    )
    op.bulk_insert(pack_table, get_packs())

    version_table = sa.table(
        "rule_set_versions",
        sa.column("id", sa.String), sa.column("rule_pack_id", sa.String), sa.column("org_id", sa.String),
        sa.column("version", sa.Integer), sa.column("status", sa.String), sa.column("published_by", sa.String),
        sa.column("published_at", sa.DateTime(timezone=True)), sa.column("changelog", sa.String),
    )
    op.bulk_insert(version_table, get_versions())

    rule_table = sa.table(
        "rules",
        sa.column("id", sa.String), sa.column("rule_set_version_id", sa.String), sa.column("org_id", sa.String),
        sa.column("rule_key", sa.String), sa.column("name", sa.String), sa.column("trigger_type", sa.String),
        sa.column("config", sa.JSON), sa.column("exemption_code_id", sa.String),
        sa.column("exemption_library_code", sa.String), sa.column("priority", sa.Integer),
        sa.column("confidence_policy", sa.String), sa.column("exclusions", sa.JSON), sa.column("scope", sa.String),
        sa.column("source_ref", sa.String), sa.column("status", sa.String),
    )
    op.bulk_insert(rule_table, get_rules())


def downgrade() -> None:
    ids = [r["id"] for r in get_rules()]
    op.execute(sa.text("DELETE FROM rules WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True)), {"ids": ids})
    version_ids = [v["id"] for v in get_versions()]
    op.execute(
        sa.text("DELETE FROM rule_set_versions WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True)),
        {"ids": version_ids},
    )
    pack_ids = [p["id"] for p in get_packs()]
    op.execute(
        sa.text("DELETE FROM rule_packs WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True)),
        {"ids": pack_ids},
    )
