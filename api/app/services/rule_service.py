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

import re
from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, NotFoundError
from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.llm.provider import get_provider
from app.models.document import Document
from app.models.exemption_code import ExemptionCode
from app.models.redaction_candidate import RedactionCandidate
from app.models.rule import Rule, RulePack, RuleSetVersion
from app.pipeline.extract import extract_pdf
from app.pipeline.nl_rule_edit import PROMPT_VERSION as NL_EDIT_PROMPT_VERSION
from app.pipeline.nl_rule_edit import ProposedRuleChange, run_nl_edit
from app.pipeline.rule_engine import DETERMINISTIC_TRIGGER_TYPES, run_rule
from app.schemas.rule import RuleCreate, RulePackCreate, RulePatch
from app.services.audit_service import write_audit_event
from app.storage import get_store


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


async def _published_version_for_pack(session: AsyncSession, rule_pack_id: str) -> RuleSetVersion | None:
    result = await session.execute(
        select(RuleSetVersion).where(RuleSetVersion.rule_pack_id == rule_pack_id, RuleSetVersion.status == "published")
    )
    return result.scalars().first()


async def run_test_bench(
    session: AsyncSession, org_id: str, user_id: str, version_id: str, document_ids: list[str]
) -> dict:
    """specs/06-exemption-taxonomy.md § Test bench: "run draft version against selected
    sample documents; show would-be candidates + diff vs current published version."
    Deterministic rules only (regex/dictionary/entity) — llm_context rules aren't
    executed here either, same scope as app/pipeline/detect.py. Purely diagnostic: reads
    each document's original PDF fresh and runs the rule engine in-memory; nothing is
    persisted, no candidates are created."""
    version, all_rules = await get_version_with_rules(session, version_id)
    draft_rules = [r for r in all_rules if r.trigger_type in DETERMINISTIC_TRIGGER_TYPES]

    published_version = await _published_version_for_pack(session, version.rule_pack_id)
    published_rules: list[Rule] = []
    if published_version is not None and published_version.id != version.id:
        _pv, pv_rules = await get_version_with_rules(session, published_version.id)
        published_rules = [r for r in pv_rules if r.trigger_type in DETERMINISTIC_TRIGGER_TYPES]

    store = get_store()

    def _run_against(doc_id: str, rules: list[Rule]) -> dict[tuple[str, int, int, int], tuple[str, str]]:
        """Returns {(doc_id, page_no, start, end): (rule_key, text)} — keyed by span so
        draft vs. published results can be diffed by set difference."""
        document = documents_by_id.get(doc_id)
        if document is None or document.s3_key_original is None:
            return {}
        data = store.get(org_id, document.s3_key_original)
        pages = extract_pdf(data)
        spans: dict[tuple[str, int, int, int], tuple[str, str]] = {}
        for page in pages:
            for rule in rules:
                for match in run_rule(page.full_text, rule):
                    if match.excluded:
                        continue
                    spans[(doc_id, page.page_no, match.start, match.end)] = (rule.rule_key, match.text)
        return spans

    doc_result = await session.execute(select(Document).where(Document.id.in_(document_ids)))
    documents_by_id = {d.id: d for d in doc_result.scalars().all()}

    draft_spans: dict[tuple[str, int, int, int], tuple[str, str]] = {}
    published_spans: dict[tuple[str, int, int, int], tuple[str, str]] = {}
    for doc_id in document_ids:
        draft_spans.update(_run_against(doc_id, draft_rules))
        if published_rules:
            published_spans.update(_run_against(doc_id, published_rules))

    def _to_matches(spans: dict) -> list[dict]:
        return [
            {"document_id": key[0], "page_no": key[1], "rule_key": val[0], "text": val[1]}
            for key, val in spans.items()
        ]

    added_keys = set(draft_spans) - set(published_spans)
    removed_keys = set(published_spans) - set(draft_spans)
    unchanged_keys = set(draft_spans) & set(published_spans)

    result = {
        "published_version_id": published_version.id if published_version else None,
        "added": _to_matches({k: draft_spans[k] for k in added_keys}),
        "removed": _to_matches({k: published_spans[k] for k in removed_keys}),
        "unchanged": _to_matches({k: draft_spans[k] for k in unchanged_keys}),
    }

    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="rule_set_version.tested", object_type="rule_set_version", object_id=version.id,
        metadata={
            "document_ids": document_ids, "added": len(added_keys),
            "removed": len(removed_keys), "unchanged": len(unchanged_keys),
        },
    )
    await session.flush()
    return result


AI_ORIGINS = ("deterministic", "llm")
MIN_MANUAL_CLUSTER_SIZE = 2


def _normalize_pattern(raw_text: str) -> str:
    """Heuristic shape signature for grouping manual redactions that no rule caught —
    v1 is deliberately simple (digits -> '#', collapsed whitespace/case) rather than ML,
    matching specs/01 US-11: "report only; no auto-learning." Good enough to cluster
    e.g. every SSN- or case-number-shaped manual addition together."""
    normalized = re.sub(r"\d", "#", raw_text.strip().lower())
    normalized = re.sub(r"#+", "#", normalized)
    return re.sub(r"\s+", " ", normalized)


async def get_rule_improvements_report(session: AsyncSession, org_id: str) -> dict:
    """specs/05-redaction-pipeline.md: "aggregates: rejected AI candidates by
    rule/pattern, reviewer-added manual redactions clustered by text pattern ->
    'suggested rule improvements' report for admins. No automatic rule mutation."
    Computed live off `redaction_candidates` (no nightly-job runner exists yet in this
    repo) rather than a stored snapshot — same on-demand-aggregation pattern as
    app/services/dashboard_service.py. Never writes to a rule."""
    stats_result = await session.execute(
        select(
            RedactionCandidate.source_rule_key,
            func.count(RedactionCandidate.id),
            func.sum(case((RedactionCandidate.state == "rejected", 1), else_=0)),
        )
        .where(RedactionCandidate.org_id == org_id, RedactionCandidate.origin.in_(AI_ORIGINS), RedactionCandidate.source_rule_key.is_not(None))
        .group_by(RedactionCandidate.source_rule_key)
    )
    stats_rows = stats_result.all()

    rule_keys = [row[0] for row in stats_rows]
    name_by_key: dict[str, str] = {}
    if rule_keys:
        # Best-effort label only — a rule_key isn't a stable FK (rules fork across draft
        # versions), so this just grabs the most recently created match for a friendly name.
        names_result = await session.execute(
            select(Rule.rule_key, Rule.name).where(Rule.rule_key.in_(rule_keys)).order_by(Rule.created_at.desc())
        )
        for rule_key, name in names_result.all():
            name_by_key.setdefault(rule_key, name)

    rejected_by_rule = sorted(
        (
            {
                "rule_key": rule_key,
                "rule_name": name_by_key.get(rule_key),
                "total_count": total,
                "rejected_count": rejected,
                "rejection_rate": round(rejected / total, 4) if total else 0.0,
            }
            for rule_key, total, rejected in stats_rows
        ),
        key=lambda r: (r["rejected_count"], r["rejection_rate"]),
        reverse=True,
    )

    manual_result = await session.execute(
        select(RedactionCandidate.display_text_encrypted, RedactionCandidate.exemption_code_id).where(
            RedactionCandidate.org_id == org_id, RedactionCandidate.origin == "manual"
        )
    )
    manual_rows = manual_result.all()

    code_ids = {code_id for _text, code_id in manual_rows if code_id}
    code_by_id: dict[str, str] = {}
    if code_ids:
        codes_result = await session.execute(select(ExemptionCode.id, ExemptionCode.code).where(ExemptionCode.id.in_(code_ids)))
        code_by_id = {row[0]: row[1] for row in codes_result.all()}

    cipher = get_cipher()
    clusters: dict[str, dict] = {}
    for encrypted_text, code_id in manual_rows:
        plaintext = cipher.decrypt(org_id, encrypted_text)
        pattern = _normalize_pattern(plaintext)
        cluster = clusters.setdefault(pattern, {"count": 0, "sample_texts": [], "exemption_codes": set()})
        cluster["count"] += 1
        if len(cluster["sample_texts"]) < 5:
            cluster["sample_texts"].append(plaintext)
        if code_id:
            cluster["exemption_codes"].add(code_by_id.get(code_id, code_id))

    manual_clusters = sorted(
        (
            {
                "pattern": pattern,
                "count": c["count"],
                "sample_texts": c["sample_texts"],
                "exemption_codes": sorted(c["exemption_codes"]),
            }
            for pattern, c in clusters.items()
            if c["count"] >= MIN_MANUAL_CLUSTER_SIZE
        ),
        key=lambda c: c["count"],
        reverse=True,
    )

    return {
        "generated_at": datetime.now(UTC),
        "rejected_by_rule": rejected_by_rule,
        "manual_clusters": manual_clusters,
    }
