"""specs/05-redaction-pipeline.md Stage 3: Deterministic detection. Rule-engine driven
(specs/06's rules-engine self-service) — executes the org's active published
rule_set_versions (app/pipeline/rule_engine.py handles regex/dictionary/entity trigger
types) rather than the Phase 1 hardcoded Core PII pass, which this replaces.

confidence_policy (auto_high/suggest/flag_low) is stored on the resulting candidate's
detector_versions for future triage tooling, but does NOT change candidate.state or skip
review for any policy value — specs/05: "Deterministic-only findings are never
auto-approved," an invariant that predates confidence_policy existing as a field at all.

llm_context rules are explicitly out of scope here (app/pipeline/rule_engine.py's
run_rule() already returns no matches for them) — that's app/pipeline/detect_llm.py's
contextual pass, a separate piece of work not yet wired to read from the rules engine
(still uses the Phase 2 fixed app/pipeline/public_safety.py config).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.models.exemption_code import ExemptionCode, ExemptionLibrary
from app.models.organization import Organization
from app.models.redaction_candidate import RedactionCandidate
from app.models.rule import Rule, RulePack, RuleSetVersion
from app.pipeline.extract import PageExtraction, span_to_bbox
from app.pipeline.rule_engine import DETERMINISTIC_TRIGGER_TYPES, run_rule

RULE_ENGINE_VERSION = "1"

# specs/06: state-specific PII codes (seeded as "<STATE>-PII" in exemption_library) are a
# preferred override for the generic federal b(6) fallback — the same resolution
# Phase 1's hardcoded Core PII pass did, now general enough for any rule, not just b(6).
STATE_PII_OVERRIDE_FOR = {"b(6)": "-PII"}


def confidence_band(score: float) -> str:
    if score >= 0.85:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"


async def _default_rule_pack_ids(session: AsyncSession, org_id: str) -> list[str]:
    org = await session.get(Organization, org_id)
    assert org is not None
    configured = org.settings.get("default_rule_pack_ids") or []
    if configured:
        return list(configured)
    # Unconfigured — fall back to every global starter pack so detection isn't silently
    # empty. specs/07-ui-spec.md's onboarding flow pre-checks suggested packs by org
    # type; until that actually writes default_rule_pack_ids, this is the equivalent
    # safe default (matches Phase 1's old behavior of always running Core PII for
    # everyone, just generalized to all 5 starter packs instead of one hardcoded one).
    result = await session.execute(select(RulePack.id).where(RulePack.org_id.is_(None), RulePack.status == "active"))
    return [row[0] for row in result.all()]


async def get_active_rules(
    session: AsyncSession, org_id: str, rule_pack_ids: list[str] | None = None
) -> tuple[list[Rule], dict[str, int], list[str]]:
    """Resolves which rule_set_versions apply for this org, and returns their active
    deterministic rules. Returns (rules, version_number_by_rsv_id, rule_set_version_ids)
    — the last two exist for provenance: `documents.rule_set_version_ids` is "locked at
    processing" per specs/03-data-model.md, and each candidate's source_rule_version
    should name the actual published version a rule came from, not just the rule's own
    (unversioned) id.

    `rule_pack_ids`, when given, overrides the org's configured default packs —
    specs/04-api-spec.md POST /documents/{id}/process accepts an explicit
    `rule_pack_ids[]` for exactly this: re-running detection against a different pack
    selection than the org default without changing that default."""
    pack_ids = rule_pack_ids if rule_pack_ids is not None else await _default_rule_pack_ids(session, org_id)
    if not pack_ids:
        return [], {}, []

    version_result = await session.execute(
        select(RuleSetVersion)
        .where(RuleSetVersion.rule_pack_id.in_(pack_ids), RuleSetVersion.status == "published")
        .order_by(RuleSetVersion.rule_pack_id, RuleSetVersion.version.desc())
    )
    latest_by_pack: dict[str, RuleSetVersion] = {}
    for version in version_result.scalars().all():
        latest_by_pack.setdefault(version.rule_pack_id, version)
    if not latest_by_pack:
        return [], {}, []

    version_ids = [v.id for v in latest_by_pack.values()]
    version_number_by_rsv_id = {v.id: v.version for v in latest_by_pack.values()}

    rules_result = await session.execute(
        select(Rule).where(
            Rule.rule_set_version_id.in_(version_ids), Rule.status == "active",
            Rule.trigger_type.in_(DETERMINISTIC_TRIGGER_TYPES),
        )
    )
    return list(rules_result.scalars().all()), version_number_by_rsv_id, version_ids


async def _resolve_exemption_code_ids(session: AsyncSession, org_id: str, rules: list[Rule]) -> dict[str, str | None]:
    """One lookup per distinct exemption_library_code referenced (not one per rule, per
    page) — matches app/services/exemption_service.find_org_code_by_library_code's
    resolution, plus the state-PII-preferred-override Phase 1 already did for b(6)."""
    org = await session.get(Organization, org_id)
    assert org is not None

    library_codes = {r.exemption_library_code for r in rules if r.exemption_library_code}
    resolved: dict[str, str | None] = {}
    for library_code in library_codes:
        override_suffix = STATE_PII_OVERRIDE_FOR.get(library_code)
        code_id = None
        if override_suffix:
            state_code = f"{org.jurisdiction_state}{override_suffix}"
            result = await session.execute(
                select(ExemptionCode)
                .join(ExemptionLibrary, ExemptionCode.library_id == ExemptionLibrary.id)
                .where(ExemptionCode.org_id == org_id, ExemptionLibrary.code == state_code)
            )
            match = result.scalars().first()
            code_id = match.id if match else None
        if code_id is None:
            result = await session.execute(
                select(ExemptionCode)
                .join(ExemptionLibrary, ExemptionCode.library_id == ExemptionLibrary.id)
                .where(ExemptionCode.org_id == org_id, ExemptionLibrary.code == library_code)
            )
            match = result.scalars().first()
            code_id = match.id if match else None
        resolved[library_code] = code_id
    return resolved


async def detect_page(
    session: AsyncSession, org_id: str, doc_id: str, page: PageExtraction,
    rules: list[Rule], version_number_by_rsv_id: dict[str, int],
) -> list[RedactionCandidate]:
    cipher = get_cipher()
    exemption_code_ids = await _resolve_exemption_code_ids(session, org_id, rules)

    candidates = []
    for rule in rules:
        for match in run_rule(page.full_text, rule):
            if match.excluded:
                continue  # specs/06: exclusion hits are logged (test bench), not created as candidates
            bbox = span_to_bbox(page.word_spans, match.start, match.end)
            if bbox is None:
                continue  # NLP/regex span didn't line up with any extracted word — skip rather than guess

            exemption_code_id = rule.exemption_code_id
            if exemption_code_id is None and rule.exemption_library_code:
                exemption_code_id = exemption_code_ids.get(rule.exemption_library_code)

            candidate = RedactionCandidate(
                id=new_id("cand"), org_id=org_id, doc_id=doc_id, page_no=page.page_no, bbox=bbox,
                text_span={"start": match.start, "end": match.end},
                display_text_encrypted=cipher.encrypt(org_id, match.text),
                origin="deterministic", source_rule_key=rule.rule_key,
                source_rule_version=str(version_number_by_rsv_id.get(rule.rule_set_version_id, "")),
                exemption_code_id=exemption_code_id, confidence=confidence_band(match.score),
                state="suggested",
                detector_versions={
                    "rule_engine_version": RULE_ENGINE_VERSION, "rule_id": rule.id,
                    "confidence_policy": rule.confidence_policy,
                },
            )
            session.add(candidate)
            candidates.append(candidate)
    return candidates
