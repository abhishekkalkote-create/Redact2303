"""specs/06-exemption-taxonomy.md § Versioning & defensibility: "publish is immutable
(edit attempt creates new draft)." Exercises the real starter-pack seed data (migration
0008) as the clone source, matching how an org would actually use this in production."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.schemas.rule import RuleCreate, RulePackCreate, RulePatch
from app.services.rule_service import (
    add_rule,
    create_draft_version,
    create_rule_pack,
    delete_rule,
    get_version_with_rules,
    list_rule_packs,
    list_versions_for_pack,
    patch_rule,
    publish_version,
)
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
async def test_list_rule_packs_includes_starter_packs(db_session: AsyncSession) -> None:
    org_id, user_id = "org_rule_1", "usr_rule_1"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        packs = await list_rule_packs(db_session)
        names = {p.name for p in packs}
        assert "Core PII" in names
        assert "Legal Privilege" in names


@pytest.mark.asyncio
async def test_clone_starter_pack_copies_rules_into_new_org_owned_draft(db_session: AsyncSession) -> None:
    org_id, user_id = "org_rule_2", "usr_rule_2"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        pack = await create_rule_pack(
            db_session, org_id, user_id,
            RulePackCreate(name="My Legal Pack", category="legal", clone_from_pack_id="rpk_legal"),
        )
        assert pack.org_id == org_id
        assert pack.cloned_from_pack_id == "rpk_legal"

    async with db_session.begin():
        await set_org(db_session, org_id)
        versions = await list_versions_for_pack(db_session, pack.id)
        assert len(versions) == 1
        assert versions[0].status == "draft"
        _version, rules = await get_version_with_rules(db_session, versions[0].id)
        rule_keys = {r.rule_key for r in rules}
        assert rule_keys == {"LP-1", "LP-2", "LP-3"}
        assert all(r.org_id == org_id for r in rules), "cloned rules must belong to the cloning org, not the source"


@pytest.mark.asyncio
async def test_create_custom_pack_without_clone_starts_empty(db_session: AsyncSession) -> None:
    org_id, user_id = "org_rule_3", "usr_rule_3"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        pack = await create_rule_pack(db_session, org_id, user_id, RulePackCreate(name="Custom", category="custom"))
        versions = await list_versions_for_pack(db_session, pack.id)
        _version, rules = await get_version_with_rules(db_session, versions[0].id)
        assert rules == []


@pytest.mark.asyncio
async def test_cannot_add_rule_directly_to_a_global_starter_version(db_session: AsyncSession) -> None:
    org_id, user_id = "org_rule_4", "usr_rule_4"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        with pytest.raises(ApiError) as exc_info:
            await add_rule(
                db_session, org_id, user_id, "rsv_legal_v1",
                RuleCreate(rule_key="LP-99", name="Sneaky", trigger_type="dictionary", config={"terms": ["x"]}),
            )
        assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_editing_a_published_version_forks_a_new_draft_and_preserves_other_rules(db_session: AsyncSession) -> None:
    org_id, user_id = "org_rule_5", "usr_rule_5"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        pack = await create_rule_pack(
            db_session, org_id, user_id,
            RulePackCreate(name="My Legal Pack", category="legal", clone_from_pack_id="rpk_legal"),
        )
        versions = await list_versions_for_pack(db_session, pack.id)
        draft = versions[0]
        published = await publish_version(db_session, org_id, user_id, draft.id, "v1 go-live")
        assert published.status == "published"

    async with db_session.begin():
        await set_org(db_session, org_id)
        _v, rules_before = await get_version_with_rules(db_session, published.id)
        target_rule = next(r for r in rules_before if r.rule_key == "LP-1")

        updated = await patch_rule(db_session, org_id, user_id, target_rule.id, RulePatch(name="Renamed LP-1"))
        assert updated.rule_set_version_id != target_rule.rule_set_version_id, "must land in a NEW forked draft"
        assert updated.name == "Renamed LP-1"

    async with db_session.begin():
        await set_org(db_session, org_id)
        versions_after = await list_versions_for_pack(db_session, pack.id)
        assert len(versions_after) == 2
        draft_version = next(v for v in versions_after if v.status == "draft")
        assert draft_version.version == 2

        _v, forked_rules = await get_version_with_rules(db_session, draft_version.id)
        forked_keys = {r.rule_key: r.name for r in forked_rules}
        assert forked_keys["LP-1"] == "Renamed LP-1"
        assert "LP-2" in forked_keys, "the OTHER rules must have been cloned into the fork too, unedited"

        # The original published version must be untouched (immutable).
        _v, original_rules = await get_version_with_rules(db_session, published.id)
        original_lp1 = next(r for r in original_rules if r.rule_key == "LP-1")
        assert original_lp1.name != "Renamed LP-1"


@pytest.mark.asyncio
async def test_delete_rule_on_published_version_forks_and_removes_only_that_rule(db_session: AsyncSession) -> None:
    org_id, user_id = "org_rule_6", "usr_rule_6"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        pack = await create_rule_pack(
            db_session, org_id, user_id,
            RulePackCreate(name="My Legal Pack", category="legal", clone_from_pack_id="rpk_legal"),
        )
        versions = await list_versions_for_pack(db_session, pack.id)
        published = await publish_version(db_session, org_id, user_id, versions[0].id, None)

    async with db_session.begin():
        await set_org(db_session, org_id)
        _v, rules_before = await get_version_with_rules(db_session, published.id)
        target = next(r for r in rules_before if r.rule_key == "LP-2")
        await delete_rule(db_session, org_id, user_id, target.id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        versions_after = await list_versions_for_pack(db_session, pack.id)
        draft_version = next(v for v in versions_after if v.status == "draft")
        _v, forked_rules = await get_version_with_rules(db_session, draft_version.id)
        forked_keys = {r.rule_key for r in forked_rules}
        assert forked_keys == {"LP-1", "LP-3"}


@pytest.mark.asyncio
async def test_publish_requires_draft_status(db_session: AsyncSession) -> None:
    org_id, user_id = "org_rule_7", "usr_rule_7"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        pack = await create_rule_pack(db_session, org_id, user_id, RulePackCreate(name="Custom", category="custom"))
        versions = await list_versions_for_pack(db_session, pack.id)
        published = await publish_version(db_session, org_id, user_id, versions[0].id, None)

    async with db_session.begin():
        await set_org(db_session, org_id)
        with pytest.raises(ApiError) as exc_info:
            await publish_version(db_session, org_id, user_id, published.id, None)
        assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_publishing_a_new_draft_archives_the_previous_published_version(db_session: AsyncSession) -> None:
    org_id, user_id = "org_rule_8", "usr_rule_8"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        pack = await create_rule_pack(db_session, org_id, user_id, RulePackCreate(name="Custom", category="custom"))
        versions = await list_versions_for_pack(db_session, pack.id)
        v1 = await publish_version(db_session, org_id, user_id, versions[0].id, "v1")

    async with db_session.begin():
        await set_org(db_session, org_id)
        v2_draft = await create_draft_version(db_session, org_id, user_id, pack.id)
        v2 = await publish_version(db_session, org_id, user_id, v2_draft.id, "v2")
        assert v2.status == "published"

    async with db_session.begin():
        await set_org(db_session, org_id)
        versions_after = await list_versions_for_pack(db_session, pack.id)
        by_id = {v.id: v.status for v in versions_after}
        assert by_id[v1.id] == "archived"
        assert by_id[v2.id] == "published"


@pytest.mark.asyncio
async def test_create_draft_version_rejects_if_one_already_open(db_session: AsyncSession) -> None:
    org_id, user_id = "org_rule_9", "usr_rule_9"
    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        pack = await create_rule_pack(db_session, org_id, user_id, RulePackCreate(name="Custom", category="custom"))

    async with db_session.begin():
        await set_org(db_session, org_id)
        with pytest.raises(ApiError) as exc_info:
            await create_draft_version(db_session, org_id, user_id, pack.id)
        assert exc_info.value.status_code == 422
