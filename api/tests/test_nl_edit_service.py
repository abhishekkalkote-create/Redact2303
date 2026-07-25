"""app.services.rule_service.nl_edit_version — DB-level integration: real existing
rules (cloned starter-pack rules) summarized into the prompt, real org exemption codes
as the allowed-code set, and a real audit trail entry recording the instruction as
provenance."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.provider import FakeLLMProvider
from app.schemas.rule import RulePackCreate
from app.services.exemption_service import clone_library_for_org
from app.services.rule_service import create_rule_pack, list_versions_for_pack, nl_edit_version
from tests.conftest import set_org


async def _seed_org_and_user(session: AsyncSession, org_id: str, user_id: str) -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'other', 'pilot', 'trialing', '{}')"
        ),
        {"id": org_id},
    )
    await session.execute(
        text(
            "INSERT INTO users (id, email, name, status) VALUES "
            "(:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )


@pytest.mark.asyncio
async def test_nl_edit_version_proposes_change_and_audits_instruction(db_session: AsyncSession, monkeypatch) -> None:
    org_id, user_id = "org_nl_1", "usr_nl_1"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)
        await clone_library_for_org(db_session, org_id, "WA")

    async with db_session.begin():
        await set_org(db_session, org_id)
        pack = await create_rule_pack(
            db_session, org_id, user_id,
            RulePackCreate(name="My Public Safety", category="public_safety", clone_from_pack_id="rpk_public_safety"),
        )
        versions = await list_versions_for_pack(db_session, pack.id)
        version_id = versions[0].id

    fake_response = (
        '{"changes": [{"action": "new", "rule_key": "PS-CUSTOM-1", "name": "Witness cell phone", '
        '"trigger_type": "regex", "config": {"pattern": "\\\\d{3}-\\\\d{3}-\\\\d{4}", '
        '"context_words": ["cell"]}, "exemption_code": "7(C)", '
        '"rationale": "Redact witness cell numbers, not office lines"}]}'
    )
    fake_provider = FakeLLMProvider(canned_responses=[("witness cell phone", fake_response)])
    monkeypatch.setattr("app.services.rule_service.get_provider", lambda: fake_provider)

    async with db_session.begin():
        await set_org(db_session, org_id)
        proposals, prompt_version = await nl_edit_version(
            db_session, org_id, user_id, version_id,
            "Redact witness cell phone numbers but not office switchboard numbers",
        )

    assert prompt_version == "1"
    assert len(proposals) == 1
    assert proposals[0].is_valid
    assert proposals[0].rule_key == "PS-CUSTOM-1"
    assert len(fake_provider.calls) == 1
    # Existing rules (cloned from the starter pack) must appear in the prompt sent to the LLM.
    assert "PS-1" in fake_provider.calls[0][1]

    async with db_session.begin():
        await set_org(db_session, org_id)
        result = await db_session.execute(
            text(
                "SELECT metadata FROM audit_events WHERE action = 'rule_set_version.nl_edit_proposed' "
                "AND object_id = :version_id"
            ),
            {"version_id": version_id},
        )
        row = result.one()
        assert row.metadata["instruction"] == "Redact witness cell phone numbers but not office switchboard numbers"
        assert row.metadata["valid_proposals"] == 1


@pytest.mark.asyncio
async def test_nl_edit_version_rejects_code_not_in_org_taxonomy(db_session: AsyncSession, monkeypatch) -> None:
    org_id, user_id = "org_nl_2", "usr_nl_2"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)
        await clone_library_for_org(db_session, org_id, "WA")

    async with db_session.begin():
        await set_org(db_session, org_id)
        pack = await create_rule_pack(db_session, org_id, user_id, RulePackCreate(name="Custom", category="custom"))
        versions = await list_versions_for_pack(db_session, pack.id)
        version_id = versions[0].id

    fake_response = (
        '{"changes": [{"action": "new", "rule_key": "X-1", "name": "x", "trigger_type": "dictionary", '
        '"config": {"terms": ["x"]}, "exemption_code": "not-a-real-code", "rationale": "x"}]}'
    )
    fake_provider = FakeLLMProvider(canned_responses=[("test instruction", fake_response)])
    monkeypatch.setattr("app.services.rule_service.get_provider", lambda: fake_provider)

    async with db_session.begin():
        await set_org(db_session, org_id)
        proposals, _prompt_version = await nl_edit_version(db_session, org_id, user_id, version_id, "test instruction")

    assert not proposals[0].is_valid
