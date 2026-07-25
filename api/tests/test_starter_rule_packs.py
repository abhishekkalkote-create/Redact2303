"""specs/06-exemption-taxonomy.md § Starter packs — integration test of the real seeded
migration 0008 rows running through the real app.pipeline.rule_engine, against realistic
sample text. Not a unit test of the engine (test_rule_engine.py already covers that) —
this exists to catch seed-data mistakes (wrong trigger config, wrong exemption code) that
per-function unit tests can't."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rule import Rule, RulePack, RuleSetVersion
from app.pipeline.rule_engine import run_rule
from tests.conftest import set_org


async def _rules_for_pack(session: AsyncSession, pack_id: str) -> list[Rule]:
    result = await session.execute(
        select(Rule)
        .join(RuleSetVersion, Rule.rule_set_version_id == RuleSetVersion.id)
        .join(RulePack, RuleSetVersion.rule_pack_id == RulePack.id)
        .where(RulePack.id == pack_id, RuleSetVersion.status == "published")
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_starter_packs_exist_published_and_global(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await set_org(db_session, "org_seed_check")  # any org context — must see global rows
        result = await db_session.execute(select(RulePack).where(RulePack.org_id.is_(None)))
        packs = {p.id: p for p in result.scalars().all()}

    assert set(packs) == {"rpk_core_pii", "rpk_public_safety", "rpk_hr", "rpk_legal", "rpk_health"}
    assert all(p.status == "active" for p in packs.values())


@pytest.mark.asyncio
async def test_core_pii_rules_detect_real_pii_in_sample_text(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await set_org(db_session, "org_seed_check")
        rules = await _rules_for_pack(db_session, "rpk_core_pii")

    text = (
        "Applicant SSN: 234-56-7890. Contact email: jane.doe@example.com, "
        "phone 206-555-0199. DOB: January 5, 1990. Home address: lives at 123 Main St."
    )
    all_matches = [m for rule in rules for m in run_rule(text, rule)]
    kept = [m for m in all_matches if not m.excluded]

    matched_by_key = {m.rule_key: m.text for m in kept}
    assert "234-56-7890" in matched_by_key["CPII-1"]
    assert "jane.doe@example.com" in matched_by_key["CPII-5"]
    assert "1990" in matched_by_key["CPII-8"]


@pytest.mark.asyncio
async def test_public_safety_informant_code_and_open_case_number(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await set_org(db_session, "org_seed_check")
        rules = await _rules_for_pack(db_session, "rpk_public_safety")

    text = "Source CI-4471 provided the tip. This remains an open case #2026-11384."
    all_matches = [m for rule in rules for m in run_rule(text, rule)]
    kept = {m.rule_key: m.text for m in all_matches if not m.excluded}

    assert "CI-4471" in kept["PS-2"]
    assert "2026-11384" in kept["PS-5"] or "case" in kept["PS-5"].lower()


@pytest.mark.asyncio
async def test_legal_privilege_dictionary_markers(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await set_org(db_session, "org_seed_check")
        rules = await _rules_for_pack(db_session, "rpk_legal")

    text = "This memo is privileged and confidential and reflects attorney work product."
    all_matches = [m for rule in rules for m in run_rule(text, rule)]
    matched_texts = {m.text.lower() for m in all_matches if not m.excluded}
    assert "privileged and confidential" in matched_texts
    assert "attorney work product" in matched_texts


@pytest.mark.asyncio
async def test_health_mrn_regex_and_sensitive_category_dictionary(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await set_org(db_session, "org_seed_check")
        rules = await _rules_for_pack(db_session, "rpk_health")

    text = "Patient MRN: 00458213 was evaluated. Reproductive health services were discussed."
    all_matches = [m for rule in rules for m in run_rule(text, rule)]
    kept = {m.rule_key: m.text for m in all_matches if not m.excluded}
    assert "00458213" in kept["HL-2"]
    assert "reproductive health" in kept["HL-3"].lower()


@pytest.mark.asyncio
async def test_all_seed_rules_reference_a_real_federal_exemption_code(db_session: AsyncSession) -> None:
    """Every exemption_library_code on a starter rule must resolve for ANY org
    regardless of jurisdiction — only federal codes guarantee that (every org gets the
    federal library cloned; state codes are optional overrides)."""
    async with db_session.begin():
        await set_org(db_session, "org_seed_check")
        result = await db_session.execute(
            select(Rule.rule_key, Rule.exemption_library_code).join(
                RuleSetVersion, Rule.rule_set_version_id == RuleSetVersion.id
            )
        )
        rows = result.all()

    federal_codes = {"b(1)", "b(2)", "b(3)", "b(4)", "b(5)", "b(6)", "7(A)", "7(B)", "7(C)", "7(D)", "7(E)", "7(F)", "b(8)", "b(9)"}
    for rule_key, code in rows:
        assert code in federal_codes, f"{rule_key} references non-federal code {code!r}"
