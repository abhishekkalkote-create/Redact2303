"""Adds Pennsylvania to the exemption_library (specs/06-exemption-taxonomy.md: "library
format makes adding states data-only" - see migration 0003's docstring for the original
five states, and this file for the same pattern applied to PA).

PA is the primary pilot jurisdiction (2026-09-07) but wasn't in the seeded library at
all, nor in web/.../onboarding/page.tsx's STATES dropdown (fixed separately, frontend-only).

Citations verified via web research against the actual statute text (Pennsylvania's
Right-to-Know Law, 65 P.S. § 67.101 et seq.), not invented - matching migration 0003's
own standard. Five categories, matching the same scope TX/FL/NY got in that migration:

- PA-PII: § 67.708(b)(6)(i) - SSN, driver's license number, personal financial info,
  home/cellular/personal phone numbers, personal e-mail addresses, employee number or
  other confidential personal ID number (subpart (A)); also spouse's name/marital
  status/beneficiary or dependent info (subpart (B)).
- PA-INVESTIGATIVE: § 67.708(b)(16) - records relating to or resulting in a criminal
  investigation, including complaints of potential criminal conduct and investigative
  materials/notes/correspondence/videos/reports.
- PA-CONFIDENTIAL-SOURCE: § 67.708(b)(16)(iii) - identity of a confidential source, or
  of a suspect who hasn't been charged to whom confidentiality has been promised.
- PA-VICTIM: § 67.708(b)(16)(v) - victim information, including anything that would
  jeopardize the victim's safety. (The statute text itself only says "victim", not
  "witness" - not labeled VICTIM-WITNESS like some other states' combined categories,
  to avoid claiming coverage this specific subsection doesn't state.)
- PA-PERSONNEL: § 67.708(b)(6)(i)(C) - home address of a law enforcement officer or judge.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _row(id_: str, code: str, level: str, state: str | None, label: str, citation: str, description: str) -> dict:
    return {
        "id": id_,
        "code": code,
        "level": level,
        "state": state,
        "label": label,
        "statute_citation": citation,
        "description": description,
        "guidance_url": None,
        "status": "active",
    }


PA_ROWS = [
    _row("exl_pa_pii", "PA-PII", "state", "PA", "Personal identifying information",
         "65 P.S. § 67.708(b)(6)(i)",
         "SSN, driver's license number, personal financial information, home/cellular/personal phone "
         "numbers, personal e-mail addresses, employee number or other confidential personal ID number; "
         "also spouse's name/marital status/beneficiary or dependent information."),
    _row("exl_pa_investigative", "PA-INVESTIGATIVE", "state", "PA", "Criminal investigative records",
         "65 P.S. § 67.708(b)(16)",
         "Records relating to or resulting in a criminal investigation, including complaints of potential "
         "criminal conduct and investigative materials, notes, correspondence, videos, and reports."),
    _row("exl_pa_confidential_source", "PA-CONFIDENTIAL-SOURCE", "state", "PA", "Confidential source",
         "65 P.S. § 67.708(b)(16)(iii)",
         "Identity of a confidential source, or of a suspect who has not been charged with an offense to "
         "whom confidentiality has been promised."),
    _row("exl_pa_victim", "PA-VICTIM", "state", "PA", "Victim identity/safety",
         "65 P.S. § 67.708(b)(16)(v)",
         "Victim information, including any information that would jeopardize the safety of the victim."),
    _row("exl_pa_personnel", "PA-PERSONNEL", "state", "PA", "Law enforcement/judicial home address",
         "65 P.S. § 67.708(b)(6)(i)(C)",
         "Home address of a law enforcement officer or judge."),
]


def upgrade() -> None:
    table = sa.table(
        "exemption_library",
        sa.column("id", sa.String),
        sa.column("code", sa.String),
        sa.column("level", sa.String),
        sa.column("state", sa.String),
        sa.column("label", sa.String),
        sa.column("statute_citation", sa.String),
        sa.column("description", sa.String),
        sa.column("guidance_url", sa.String),
        sa.column("status", sa.String),
    )
    op.bulk_insert(table, PA_ROWS)


def downgrade() -> None:
    ids = [row["id"] for row in PA_ROWS]
    op.execute(
        sa.text("DELETE FROM exemption_library WHERE id IN :ids").bindparams(
            sa.bindparam("ids", expanding=True)
        ),
        {"ids": ids},
    )
