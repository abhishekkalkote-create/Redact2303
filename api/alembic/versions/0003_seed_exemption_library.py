"""Seed the global exemption_library (specs/06-exemption-taxonomy.md).

Deliberately PARTIAL, not fabricated: federal FOIA exemptions are well-established public
law (5 U.S.C. § 552(b), quoted directly in specs/06-exemption-taxonomy.md). WA and CA
citations are the exact ones given in that same spec file. TX/FL/NY citations were verified
via web research (not invented) against 5 categories only — the other ~7 categories per
state (juvenile records, medical/health, deliberative/privileged, security plans, trade
secrets, other-statute catch-all, specific items) are NOT seeded here; adding them is
data-only (insert more rows), matching the spec's own "library format makes adding states
data-only" framing. NY's peace-officer personnel exemption (Civil Rights Law former § 50-a)
was repealed in 2020 — seeded as "no dedicated statute" rather than citing dead law.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
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


FEDERAL = [
    _row("exl_fed_b1", "b(1)", "federal", None, "National security / classified",
         "5 U.S.C. § 552(b)(1)", "Classified national defense or foreign policy information."),
    _row("exl_fed_b2", "b(2)", "federal", None, "Internal personnel rules",
         "5 U.S.C. § 552(b)(2)", "Related solely to internal personnel rules and practices."),
    _row("exl_fed_b3", "b(3)", "federal", None, "Exempt by other statute",
         "5 U.S.C. § 552(b)(3)", "Specifically exempted by another statute; requires the statute sub-citation."),
    _row("exl_fed_b4", "b(4)", "federal", None, "Trade secrets / confidential commercial",
         "5 U.S.C. § 552(b)(4)", "Trade secrets and privileged or confidential commercial/financial information."),
    _row("exl_fed_b5", "b(5)", "federal", None, "Deliberative process / privilege",
         "5 U.S.C. § 552(b)(5)", "Inter/intra-agency memoranda: deliberative process, attorney-client, work product."),
    _row("exl_fed_b6", "b(6)", "federal", None, "Personal privacy",
         "5 U.S.C. § 552(b)(6)", "Personnel, medical, and similar files whose disclosure would invade personal privacy."),
    _row("exl_fed_b7a", "7(A)", "federal", None, "Pending enforcement proceedings",
         "5 U.S.C. § 552(b)(7)(A)", "Could reasonably be expected to interfere with enforcement proceedings."),
    _row("exl_fed_b7b", "7(B)", "federal", None, "Fair trial / impartial adjudication",
         "5 U.S.C. § 552(b)(7)(B)", "Would deprive a person of a right to a fair trial or impartial adjudication."),
    _row("exl_fed_b7c", "7(C)", "federal", None, "Law-enforcement personal privacy",
         "5 U.S.C. § 552(b)(7)(C)", "Could reasonably be expected to constitute an unwarranted invasion of personal privacy."),
    _row("exl_fed_b7d", "7(D)", "federal", None, "Confidential source",
         "5 U.S.C. § 552(b)(7)(D)", "Could reasonably be expected to disclose the identity of a confidential source."),
    _row("exl_fed_b7e", "7(E)", "federal", None, "Techniques / procedures",
         "5 U.S.C. § 552(b)(7)(E)", "Would disclose investigative techniques/procedures or risk circumvention of law."),
    _row("exl_fed_b7f", "7(F)", "federal", None, "Endangerment of life or safety",
         "5 U.S.C. § 552(b)(7)(F)", "Could reasonably be expected to endanger the life or physical safety of any individual."),
    _row("exl_fed_b8", "b(8)", "federal", None, "Financial institution exams",
         "5 U.S.C. § 552(b)(8)", "Contained in or related to examination/operation/condition reports on financial institutions."),
    _row("exl_fed_b9", "b(9)", "federal", None, "Wells data",
         "5 U.S.C. § 552(b)(9)", "Geological and geophysical information and data, including maps, concerning wells."),
]

# category keys shared across states, matching specs/06-exemption-taxonomy.md's list —
# only PII / law-enforcement investigative / victim-witness / confidential-informant /
# personnel are seeded (verified citations); the rest are intentionally absent, not wrong.
STATE_ROWS = [
    # WA and CA: citations given verbatim in specs/06-exemption-taxonomy.md itself.
    _row("exl_wa_investigative", "WA-INVESTIGATIVE", "state", "WA", "Investigative records",
         "RCW 42.56.240(1)", "Law enforcement investigative records exemption."),
    _row("exl_ca_investigative", "CA-INVESTIGATIVE", "state", "CA", "Investigative records",
         "Cal. Gov. Code § 7923.600", "Law enforcement investigative records exemption."),

    # Texas — Gov't Code Ch. 552 (Public Information Act) unless noted; verified via web
    # research, not memory.
    _row("exl_tx_pii", "TX-PII", "state", "TX", "Personal identifying information",
         "Tex. Gov't Code § 552.147; § 552.11765; § 552.130",
         "SSN (general and license-holder), DOB, driver's license/motor vehicle records."),
    _row("exl_tx_investigative", "TX-INVESTIGATIVE", "state", "TX", "Law enforcement investigative records",
         "Tex. Gov't Code § 552.108",
         "Certain law enforcement, corrections, and prosecutorial information; also covers confidential informants (no separate TX statute)."),
    _row("exl_tx_victim_witness", "TX-VICTIM-WITNESS", "state", "TX", "Sexual-offense victim identity",
         "Tex. Code Crim. Proc. art. 57.02",
         "Pseudonym / identity protection for victims of sexual offenses (Code of Criminal Procedure, not Gov't Code)."),
    _row("exl_tx_personnel", "TX-PERSONNEL", "state", "TX", "Peace officer personal information",
         "Tex. Gov't Code § 552.117; § 552.1175",
         "Home address/phone/SSN/family info for peace officers and other sensitive-function officials."),

    # Florida — Fla. Stat. Ch. 119 (Public Records Act).
    _row("exl_fl_pii", "FL-PII", "state", "FL", "Personal identifying information",
         "Fla. Stat. § 119.071(5)", "Social security numbers held by agencies."),
    _row("exl_fl_investigative", "FL-INVESTIGATIVE", "state", "FL", "Active criminal investigative/intelligence info",
         "Fla. Stat. § 119.071(2)(a)",
         "Active criminal investigative or intelligence information; also covers confidential informants (same subsection, no separate citation)."),
    _row("exl_fl_victim_witness", "FL-VICTIM-WITNESS", "state", "FL", "Sexual/child-abuse victim identity",
         "Fla. Stat. § 119.071(2)(h)",
         "Identity of victims under ch. 794 (sexual battery), ch. 800 (lewd/lascivious), ch. 827 (child abuse)."),
    _row("exl_fl_personnel", "FL-PERSONNEL", "state", "FL", "Law enforcement personnel information",
         "Fla. Stat. § 119.071(4)(d)",
         "Home address/phone/SSN/photo of law enforcement officers and related personnel."),

    # New York — Public Officers Law Art. 6 (FOIL) unless noted.
    _row("exl_ny_pii", "NY-PII", "state", "NY", "Personal identifying information",
         "N.Y. Pub. Off. Law § 96-a; § 87(2)(b)",
         "SSN disclosure restrictions (Personal Privacy Protection Law) and the general FOIL privacy exemption."),
    _row("exl_ny_investigative", "NY-INVESTIGATIVE", "state", "NY", "Law enforcement investigative records",
         "N.Y. Pub. Off. Law § 87(2)(e)(i)", "Records that would interfere with a law enforcement investigation."),
    _row("exl_ny_confidential_source", "NY-CONFIDENTIAL-SOURCE", "state", "NY", "Confidential source",
         "N.Y. Pub. Off. Law § 87(2)(e)(iii)", "Would identify a confidential source."),
    _row("exl_ny_victim_witness", "NY-VICTIM-WITNESS", "state", "NY", "Sex-offense victim identity",
         "N.Y. Civ. Rights Law § 50-b", "Identity protection for victims of sex offenses (Civil Rights Law, not Public Officers Law)."),
    _row("exl_ny_personnel", "NY-PERSONNEL", "state", "NY", "Police personnel records — no dedicated statute",
         "N.Y. Pub. Off. Law § 87(2)(b) (general privacy balancing test)",
         "Former Civil Rights Law § 50-a (police personnel/disciplinary shield) was REPEALED June 2020. "
         "Disciplinary records are now presumptively disclosable under FOIL's general privacy balancing test, "
         "with redaction limited to 'technical infractions' and similar. Do not cite § 50-a as current law."),
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
    op.bulk_insert(table, FEDERAL + STATE_ROWS)


def downgrade() -> None:
    ids = [row["id"] for row in FEDERAL + STATE_ROWS]
    op.execute(
        sa.text("DELETE FROM exemption_library WHERE id IN :ids").bindparams(
            sa.bindparam("ids", expanding=True)
        ),
        {"ids": ids},
    )
