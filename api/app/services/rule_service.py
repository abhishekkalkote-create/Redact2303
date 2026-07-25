"""specs/06-exemption-taxonomy.md § Versioning & defensibility: "Rule sets: draft →
published (immutable) → archived." and "publish is immutable (edit attempt creates new
draft)."

Global starter packs (rule_pack.org_id IS NULL) are read-only templates — an org can
never edit one directly, only clone it (create_rule_pack with clone_from_pack_id) into a
fully org-owned pack first. Every mutation below operates only on org-owned packs;
attempting to touch a global one raises a clear "clone it first" error rather than
silently forking a same-shared-pack-id row that would be confusing for every other org
sharing that pack_id to reason about.

Within an org-owned pack, "edit attempt creates new draft" is real, not just documented:
adding/editing/deleting a rule against a published or archived version transparently
forks a new draft version (cloning every rule from the source), applies the edit to the
corresponding rule THERE, and returns that — the caller doesn't have to orchestrate the
fork themselves.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, NotFoundError
from app.core.ids import new_id
from app.llm.provider import get_provider
from app.models.exemption_code import ExemptionCode
from app.models.rule import Rule, RulePack, RuleSetVersion
from app.pipeline.nl_rule_edit import PROMPT_VERSION as NL_EDIT_PROMPT_VERSION
from app.pipeline.nl_rule_edit import ProposedRuleChange, run_nl_edit
from app.schemas.rule import RuleCreate, RulePackCreate, RulePatch
from app.services.audit_service import write_audit_event


async def list_rule_packs(session: AsyncSession) -> list[RulePack]:
    result = await session.execute(select(RulePack).order_by(RulePack.category, RulePack.name))
    return list(result.scalars().all())


async def _latest_version_for_pack(session: AsyncSession, rule_pack_id: str) -> RuleSetVersion | None:
    result = await session.execute(
        select(RuleSetVersion).where(RuleSetVersion.rule_pack_id == rule_pack_id).order_by(RuleSetVersion.version.desc()).limit(1)
    )
    return result.scalars().first()


async def _next_version_number(session: AsyncSession, rule_pack_id: str) -> int:
    result = await session.execute(select(func.max(RuleSetVersion.version)).where(RuleSetVersion.rule_pack_id == rule_pack_id))
    return (result.scalar() or 0) + 1


async def _clone_rules_into(session: AsyncSession, org_id: str, source_version_id: str, target_version_id: str) -> dict[str, Rule]:
    """Returns old_rule_id -> new Rule, so callers that are forking to apply one specific
    edit can find "the corresponding rule" in the clone."""
    result = await session.execute(select(Rule).where(Rule.rule_set_version_id == source_version_id))
    source_rules = list(result.scalars().all())

    id_map: dict[str, Rule] = {}
    for rule in source_rules:
        new_rule = Rule(
            id=new_id("rul"), rule_set_version_id=target_version_id, org_id=org_id, rule_key=rule.rule_key,
            name=rule.name, trigger_type=rule.trigger_type, config=rule.config,
            exemption_code_id=rule.exemption_code_id, exemption_library_code=rule.exemption_library_code,
            priority=rule.priority, confidence_policy=rule.confidence_policy, exclusions=rule.exclusions,
            scope=rule.scope, source_ref=rule.source_ref, status=rule.status,
        )
        session.add(new_rule)
        id_map[rule.id] = new_rule
    await session.flush()
    return id_map


async def create_rule_pack(session: AsyncSession, org_id: str, user_id: str, payload: RulePackCreate) -> RulePack:
    pack = RulePack(
        id=new_id("rpk"), org_id=org_id, name=payload.name, description=payload.description,
        category=payload.category, status="active", cloned_from_pack_id=payload.clone_from_pack_id,
    )
    session.add(pack)
    version = RuleSetVersion(id=new_id("rsv"), rule_pack_id=pack.id, org_id=org_id, version=1, status="draft")
    session.add(version)
    await session.flush()

    rules_cloned = 0
    if payload.clone_from_pack_id:
        source_version = await _latest_version_for_pack(session, payload.clone_from_pack_id)
        if source_version is not None:
            rules_cloned = len(await _clone_rules_into(session, org_id, source_version.id, version.id))

    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="rule_pack.created", object_type="rule_pack", object_id=pack.id,
        metadata={"cloned_from_pack_id": payload.clone_from_pack_id, "rules_cloned": rules_cloned},
    )
    await session.flush()
    await session.refresh(pack)
    return pack


async def list_versions_for_pack(session: AsyncSession, rule_pack_id: str) -> list[RuleSetVersion]:
    result = await session.execute(
        select(RuleSetVersion).where(RuleSetVersion.rule_pack_id == rule_pack_id).order_by(RuleSetVersion.version.desc())
    )
    return list(result.scalars().all())


async def get_version_with_rules(session: AsyncSession, version_id: str) -> tuple[RuleSetVersion, list[Rule]]:
    version = await session.get(RuleSetVersion, version_id)
    if version is None:
        raise NotFoundError("Rule set version not found")
    result = await session.execute(select(Rule).where(Rule.rule_set_version_id == version_id).order_by(Rule.rule_key))
    return version, list(result.scalars().all())


async def create_draft_version(session: AsyncSession, org_id: str, user_id: str, rule_pack_id: str) -> RuleSetVersion:
    """POST /rule-packs/{id}/versions — "new draft from current" (specs/04-api-spec.md)."""
    pack = await session.get(RulePack, rule_pack_id)
    if pack is None:
        raise NotFoundError("Rule pack not found")
    if pack.org_id is None:
        raise ApiError(422, "Unprocessable Entity", "Cannot create a version under a global starter pack — clone it into your org first.")

    current = await _latest_version_for_pack(session, rule_pack_id)
    if current is not None and current.status == "draft":
        raise ApiError(422, "Unprocessable Entity", f"Pack already has an open draft version ({current.id})")

    new_version = RuleSetVersion(
        id=new_id("rsv"), rule_pack_id=rule_pack_id, org_id=org_id,
        version=await _next_version_number(session, rule_pack_id), status="draft",
    )
    session.add(new_version)
    await session.flush()
    if current is not None:
        await _clone_rules_into(session, org_id, current.id, new_version.id)
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="rule_set_version.drafted", object_type="rule_set_version", object_id=new_version.id,
        metadata={"rule_pack_id": rule_pack_id, "forked_from": current.id if current else None},
    )
    await session.flush()
    await session.refresh(new_version)
    return new_version


async def _ensure_draft_version(
    session: AsyncSession, org_id: str, user_id: str, version: RuleSetVersion
) -> tuple[RuleSetVersion, dict[str, Rule]]:
    if version.org_id is None:
        raise ApiError(
            422, "Unprocessable Entity",
            "This is a global starter pack version — clone it into your org first (POST /rule-packs "
            "with clone_from_pack_id) before editing its rules.",
        )
    if version.status == "draft":
        return version, {}

    new_version = RuleSetVersion(
        id=new_id("rsv"), rule_pack_id=version.rule_pack_id, org_id=org_id,
        version=await _next_version_number(session, version.rule_pack_id), status="draft",
    )
    session.add(new_version)
    await session.flush()
    id_map = await _clone_rules_into(session, org_id, version.id, new_version.id)
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="rule_set_version.drafted", object_type="rule_set_version", object_id=new_version.id,
        metadata={"rule_pack_id": version.rule_pack_id, "forked_from": version.id, "reason": "edit_attempt_on_" + version.status},
    )
    await session.flush()
    return new_version, id_map


async def add_rule(session: AsyncSession, org_id: str, user_id: str, version_id: str, payload: RuleCreate) -> Rule:
    version = await session.get(RuleSetVersion, version_id)
    if version is None:
        raise NotFoundError("Rule set version not found")
    version, _id_map = await _ensure_draft_version(session, org_id, user_id, version)

    rule = Rule(
        id=new_id("rul"), rule_set_version_id=version.id, org_id=org_id, rule_key=payload.rule_key,
        name=payload.name, trigger_type=payload.trigger_type, config=payload.config,
        exemption_code_id=payload.exemption_code_id, exemption_library_code=payload.exemption_library_code,
        priority=payload.priority, confidence_policy=payload.confidence_policy, exclusions=payload.exclusions,
        scope=payload.scope, source_ref=payload.source_ref, status="active",
    )
    session.add(rule)
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="rule.created", object_type="rule", object_id=rule.id,
        metadata={"rule_set_version_id": version.id, "rule_key": rule.rule_key},
    )
    await session.flush()
    await session.refresh(rule)
    return rule


async def patch_rule(session: AsyncSession, org_id: str, user_id: str, rule_id: str, payload: RulePatch) -> Rule:
    rule = await session.get(Rule, rule_id)
    if rule is None:
        raise NotFoundError("Rule not found")
    version = await session.get(RuleSetVersion, rule.rule_set_version_id)
    assert version is not None
    version, id_map = await _ensure_draft_version(session, org_id, user_id, version)
    target = id_map.get(rule.id, rule)

    updates = payload.model_dump(exclude_none=True)
    for key, value in updates.items():
        setattr(target, key, value)
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="rule.updated", object_type="rule", object_id=target.id,
        metadata={"fields": list(updates), "forked_new_draft": bool(id_map)},
    )
    await session.flush()
    await session.refresh(target)
    return target


async def delete_rule(session: AsyncSession, org_id: str, user_id: str, rule_id: str) -> None:
    rule = await session.get(Rule, rule_id)
    if rule is None:
        raise NotFoundError("Rule not found")
    version = await session.get(RuleSetVersion, rule.rule_set_version_id)
    assert version is not None
    version, id_map = await _ensure_draft_version(session, org_id, user_id, version)
    target = id_map.get(rule.id, rule)

    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="rule.deleted", object_type="rule", object_id=target.id,
        metadata={"rule_key": target.rule_key, "forked_new_draft": bool(id_map)},
    )
    await session.delete(target)
    await session.flush()


async def publish_version(session: AsyncSession, org_id: str, user_id: str, version_id: str, changelog: str | None) -> RuleSetVersion:
    version = await session.get(RuleSetVersion, version_id)
    if version is None:
        raise NotFoundError("Rule set version not found")
    if version.org_id is None:
        raise ApiError(422, "Unprocessable Entity", "Cannot publish a global starter pack version.")
    if version.status != "draft":
        raise ApiError(422, "Unprocessable Entity", f"Only a draft version can be published (is {version.status})")

    # specs/06: "draft → published (immutable) → archived" — at most one published
    # version per pack at a time.
    result = await session.execute(
        select(RuleSetVersion).where(RuleSetVersion.rule_pack_id == version.rule_pack_id, RuleSetVersion.status == "published")
    )
    for previous in result.scalars().all():
        previous.status = "archived"

    version.status = "published"
    version.published_by = user_id
    version.published_at = datetime.now(UTC)
    version.changelog = changelog
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="rule_set_version.published", object_type="rule_set_version", object_id=version.id,
        metadata={"version": version.version, "changelog": changelog},
    )
    await session.flush()
    await session.refresh(version)
    return version


async def _allowed_exemption_codes(session: AsyncSession, org_id: str) -> set[str]:
    result = await session.execute(
        select(ExemptionCode.code).where(ExemptionCode.org_id == org_id, ExemptionCode.status == "active")
    )
    return {row[0] for row in result.all()}


async def nl_edit_version(
    session: AsyncSession, org_id: str, user_id: str, version_id: str, instruction: str
) -> tuple[list[ProposedRuleChange], str]:
    """specs/06: NL instruction -> LLM-proposed rule diff. Never persists anything —
    proposals are ephemeral; a human confirms via the existing rule CRUD endpoints."""
    version, rules = await get_version_with_rules(session, version_id)
    allowed_codes = await _allowed_exemption_codes(session, org_id)

    provider = get_provider()
    proposals, input_tokens, output_tokens = run_nl_edit(provider, instruction, rules, allowed_codes)

    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="rule_set_version.nl_edit_proposed", object_type="rule_set_version", object_id=version.id,
        metadata={
            "instruction": instruction, "prompt_version": NL_EDIT_PROMPT_VERSION,
            "proposals": len(proposals), "valid_proposals": sum(1 for p in proposals if p.is_valid),
            "input_tokens": input_tokens, "output_tokens": output_tokens,
        },
    )
    await session.flush()
    return proposals, NL_EDIT_PROMPT_VERSION
