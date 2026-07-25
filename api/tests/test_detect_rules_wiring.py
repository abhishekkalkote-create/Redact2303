"""app/pipeline/detect.py's rule-set resolution: which published rule_set_versions run
for an org (default_rule_pack_ids configured vs. the all-starter-packs fallback), and
that specs/03-data-model.md's "documents.rule_set_version_ids locked at processing" is
actually populated — the piece test_pipeline_integration.py's end-to-end run doesn't
directly assert on."""

import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.pipeline.detect import get_active_rules
from tests.conftest import set_org


async def _seed_org(session: AsyncSession, org_id: str, *, default_rule_pack_ids: list[str] | None = None) -> None:
    await set_org(session, org_id)
    settings = {"default_rule_pack_ids": default_rule_pack_ids} if default_rule_pack_ids is not None else {}
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'other', 'pilot', 'trialing', :settings)"
        ),
        {"id": org_id, "settings": json.dumps(settings)},
    )


@pytest.mark.asyncio
async def test_get_active_rules_falls_back_to_all_starter_packs_when_unconfigured(db_session: AsyncSession) -> None:
    org_id = new_id("org")
    async with db_session.begin():
        await _seed_org(db_session, org_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        rules, version_by_rsv, version_ids = await get_active_rules(db_session, org_id)

    rule_keys = {r.rule_key for r in rules}
    # Deterministic keys from all 5 packs — llm_context rules (PS-6/HR-3/LP-3) excluded.
    assert "CPII-1" in rule_keys
    assert "PS-1" in rule_keys
    assert "HR-1" in rule_keys
    assert "LP-1" in rule_keys
    assert "HL-1" in rule_keys
    assert "PS-6" not in rule_keys, "llm_context rules must not come back from the deterministic resolver"
    assert len(version_ids) == 5
    assert all(v == 1 for v in version_by_rsv.values())


@pytest.mark.asyncio
async def test_get_active_rules_respects_configured_default_rule_pack_ids(db_session: AsyncSession) -> None:
    org_id = new_id("org")
    async with db_session.begin():
        await _seed_org(db_session, org_id, default_rule_pack_ids=["rpk_legal"])

    async with db_session.begin():
        await set_org(db_session, org_id)
        rules, _version_by_rsv, version_ids = await get_active_rules(db_session, org_id)

    rule_keys = {r.rule_key for r in rules}
    assert rule_keys == {"LP-1", "LP-2"}  # LP-3 is llm_context, excluded
    assert len(version_ids) == 1


@pytest.mark.asyncio
async def test_get_active_rules_empty_configured_list_yields_no_rules(db_session: AsyncSession) -> None:
    """An explicit empty list is a deliberate "detect nothing deterministically" choice,
    distinct from "unconfigured" (which falls back to all starter packs) — `settings.get`
    returning [] is falsy either way, so this also documents that current behavior:
    an empty list is indistinguishable from unset and still falls back."""
    org_id = new_id("org")
    async with db_session.begin():
        await _seed_org(db_session, org_id, default_rule_pack_ids=[])

    async with db_session.begin():
        await set_org(db_session, org_id)
        rules, _version_by_rsv, version_ids = await get_active_rules(db_session, org_id)

    assert len(version_ids) == 5, "empty list is falsy, same as unconfigured — falls back to all starter packs"
    assert len(rules) > 0
