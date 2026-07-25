"""app.services.manual_service — real Postgres, real PDF extraction, real cloned
exemption taxonomy, only the LLM call itself faked (same testing boundary as
tests/test_pipeline_integration.py)."""

import fitz
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.provider import FakeLLMProvider
from app.schemas.manual import DraftRuleAcceptRequest
from app.schemas.rule import RulePackCreate
from app.services.exemption_service import clone_library_for_org
from app.services.manual_service import (
    accept_draft_rule,
    list_draft_rules,
    reject_draft_rule,
    upload_manual,
)
from app.services.rule_service import create_rule_pack
from tests.conftest import set_org


def _sample_manual_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Section 4: Confidential Sources.")
    page.insert_text((72, 130), "Officer notes must not disclose informant identities.")
    data = doc.tobytes()
    doc.close()
    return data


async def _seed_org_and_user(session: AsyncSession, org_id: str, user_id: str) -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'police', 'pilot', 'trialing', '{}')"
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
async def test_upload_manual_runs_extraction_and_creates_draft_rules(db_session: AsyncSession, monkeypatch) -> None:
    org_id, user_id = "org_manual_1", "usr_manual_1"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)
        await clone_library_for_org(db_session, org_id, "WA")

    fake_response = (
        '{"section_type": "exemptions", "draft_rules": [{"name": "Informant identity", '
        '"trigger_type": "entity", "config": {"entity_type": "PERSON"}, "exemption_code": "7(D)", '
        '"exclusions": [], "source_quote": "must not disclose informant identities", '
        '"ambiguity_notes": "confirm this applies org-wide"}]}'
    )
    fake_provider = FakeLLMProvider(canned_responses=[("Confidential Sources", fake_response)])
    monkeypatch.setattr("app.services.manual_service.get_provider", lambda: fake_provider)

    async with db_session.begin():
        await set_org(db_session, org_id)
        manual = await upload_manual(db_session, org_id, user_id, "sop.pdf", _sample_manual_pdf())
        assert manual.extraction_status == "completed"

    async with db_session.begin():
        await set_org(db_session, org_id)
        drafts = await list_draft_rules(db_session, manual.id)
        assert len(drafts) == 1
        draft = drafts[0]
        assert draft.name == "Informant identity"
        assert draft.status == "pending"
        assert draft.exemption_code_id is not None, "the LLM's '7(D)' code string must resolve to a real org exemption_code_id"
        assert "page 1" in draft.source_ref
        assert "confirm this applies org-wide" in draft.ai_notes


@pytest.mark.asyncio
async def test_accept_draft_rule_creates_real_rule_in_target_version(db_session: AsyncSession, monkeypatch) -> None:
    org_id, user_id = "org_manual_2", "usr_manual_2"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)
        await clone_library_for_org(db_session, org_id, "WA")

    fake_response = (
        '{"section_type": "exemptions", "draft_rules": [{"name": "Informant identity", '
        '"trigger_type": "entity", "config": {"entity_type": "PERSON"}, "exemption_code": "7(D)", '
        '"source_quote": "must not disclose informant identities", "ambiguity_notes": ""}]}'
    )
    fake_provider = FakeLLMProvider(canned_responses=[("Confidential Sources", fake_response)])
    monkeypatch.setattr("app.services.manual_service.get_provider", lambda: fake_provider)

    async with db_session.begin():
        await set_org(db_session, org_id)
        manual = await upload_manual(db_session, org_id, user_id, "sop.pdf", _sample_manual_pdf())
        drafts = await list_draft_rules(db_session, manual.id)
        draft = drafts[0]

        pack_result = await db_session.execute(
            text("SELECT id FROM rule_packs WHERE org_id IS NULL AND category = 'public_safety'")
        )
        starter_pack_id = pack_result.scalar_one()

    async with db_session.begin():
        await set_org(db_session, org_id)
        pack = await create_rule_pack(
            db_session, org_id, user_id,
            RulePackCreate(name="My Extracted Rules", category="public_safety", clone_from_pack_id=starter_pack_id),
        )
        version_result = await db_session.execute(text("SELECT id FROM rule_set_versions WHERE rule_pack_id = :id"), {"id": pack.id})
        version_id = version_result.scalar_one()

    async with db_session.begin():
        await set_org(db_session, org_id)
        rule = await accept_draft_rule(
            db_session, org_id, user_id, draft.id,
            DraftRuleAcceptRequest(rule_set_version_id=version_id, rule_key="EXTRACTED-1"),
        )
        assert rule.rule_key == "EXTRACTED-1"
        assert rule.trigger_type == "entity"
        assert rule.exemption_code_id == draft.exemption_code_id

    async with db_session.begin():
        await set_org(db_session, org_id)
        drafts_after = await list_draft_rules(db_session, manual.id)
        assert drafts_after[0].status == "accepted"


@pytest.mark.asyncio
async def test_reject_draft_rule_sets_status_and_note(db_session: AsyncSession, monkeypatch) -> None:
    org_id, user_id = "org_manual_3", "usr_manual_3"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)
        await clone_library_for_org(db_session, org_id, "WA")

    fake_response = (
        '{"section_type": "exemptions", "draft_rules": [{"name": "x", "trigger_type": "entity", '
        '"config": {"entity_type": "PERSON"}, "exemption_code": "7(D)", '
        '"source_quote": "must not disclose informant identities", "ambiguity_notes": ""}]}'
    )
    fake_provider = FakeLLMProvider(canned_responses=[("Confidential Sources", fake_response)])
    monkeypatch.setattr("app.services.manual_service.get_provider", lambda: fake_provider)

    async with db_session.begin():
        await set_org(db_session, org_id)
        manual = await upload_manual(db_session, org_id, user_id, "sop.pdf", _sample_manual_pdf())
        drafts = await list_draft_rules(db_session, manual.id)
        draft_id = drafts[0].id

    async with db_session.begin():
        await set_org(db_session, org_id)
        rejected = await reject_draft_rule(db_session, org_id, user_id, draft_id, "not applicable to our jurisdiction")
        assert rejected.status == "rejected"
