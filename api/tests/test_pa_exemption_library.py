"""Pennsylvania added to exemption_library 2026-09-07 (migration 0015) as the primary
pilot jurisdiction - was entirely absent before (not in the seeded library, not in the
onboarding dropdown). Citations verified via web research against the real statute text
(65 P.S. § 67.708), matching migration 0003's own standard for the original five states.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exemption_code import ExemptionCode, ExemptionLibrary
from app.models.organization import Organization
from app.services.exemption_service import clone_library_for_org
from tests.conftest import set_org


@pytest.mark.asyncio
async def test_pa_library_rows_exist_with_expected_codes(db_session: AsyncSession) -> None:
    async with db_session.begin():
        await set_org(db_session, "org_seed_check")
        result = await db_session.execute(select(ExemptionLibrary).where(ExemptionLibrary.state == "PA"))
        rows = {r.code: r for r in result.scalars().all()}

    assert set(rows) == {"PA-PII", "PA-INVESTIGATIVE", "PA-CONFIDENTIAL-SOURCE", "PA-VICTIM", "PA-PERSONNEL"}
    assert all(r.level == "state" for r in rows.values())
    assert rows["PA-PII"].statute_citation == "65 P.S. § 67.708(b)(6)(i)"
    assert rows["PA-PERSONNEL"].statute_citation == "65 P.S. § 67.708(b)(6)(i)(C)"


@pytest.mark.asyncio
async def test_cloning_for_pa_org_gets_federal_plus_pa_only(db_session: AsyncSession) -> None:
    org_id = "org_pa_pilot"
    async with db_session.begin():
        await set_org(db_session, org_id)
        db_session.add(Organization(
            id=org_id, name="PA Pilot Agency", slug="pa-pilot-agency",
            jurisdiction_state="PA", org_type="city_clerk",
        ))
        await db_session.flush()
        cloned = await clone_library_for_org(db_session, org_id, "PA")

    states_present = {c.code for c in cloned if c.code.startswith(("PA-", "TX-", "FL-", "NY-", "WA-", "CA-"))}
    assert "PA-PII" in states_present
    # No other state's codes should have been cloned in for a PA-jurisdiction org.
    assert not any(code.startswith(("TX-", "FL-", "NY-", "WA-", "CA-")) for code in states_present)
    assert any(c.code == "b(6)" for c in cloned)  # federal library still cloned regardless of jurisdiction


@pytest.mark.asyncio
async def test_pa_pii_is_preferred_over_federal_b6_for_pa_org(db_session: AsyncSession) -> None:
    """app/pipeline/detect.py's STATE_PII_OVERRIDE_FOR maps "b(6)" -> "-PII", so a PA org
    should resolve b(6)-referencing rules to its own "PA-PII" code, not the federal one -
    confirms the override mechanism just works once the PA-PII row exists, with zero
    detect.py changes (matching migration 0003's "adding states is data-only" framing)."""
    from app.models.rule import Rule
    from app.pipeline.detect import _resolve_exemption_code_ids

    org_id = "org_pa_override_check"
    async with db_session.begin():
        await set_org(db_session, org_id)
        db_session.add(Organization(
            id=org_id, name="PA Override Check", slug="pa-override-check",
            jurisdiction_state="PA", org_type="city_clerk",
        ))
        await db_session.flush()
        await clone_library_for_org(db_session, org_id, "PA")

        fake_rule = Rule(
            id="rul_fake", rule_set_version_id="rsv_core_pii_v1", org_id=None,
            rule_key="CPII-1", name="fake", trigger_type="entity",
            config={"entity_type": "US_SSN"}, exemption_code_id=None,
            exemption_library_code="b(6)", priority=100, confidence_policy="suggest",
            exclusions=[], scope="org", status="active",
        )
        resolved = await _resolve_exemption_code_ids(db_session, org_id, [fake_rule])
        picked_id = resolved["b(6)"]
        assert picked_id is not None
        picked = await db_session.get(ExemptionCode, picked_id)
        assert picked is not None
        assert picked.code == "PA-PII"
