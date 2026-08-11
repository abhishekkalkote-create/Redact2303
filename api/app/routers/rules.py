from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_org_db, require_role
from app.models.membership import Membership
from app.models.rule import Rule, RulePack, RuleSetVersion
from app.schemas.rule import (
    NlEditRequest,
    NlEditResponse,
    ProposedRuleChangeOut,
    PublishVersionRequest,
    RuleCreate,
    RuleImprovementsReportOut,
    RuleOut,
    RulePackCreate,
    RulePackOut,
    RulePatch,
    RuleSetVersionOut,
    TestBenchRequest,
    TestBenchResponse,
)
from app.services.rule_service import (
    add_rule,
    create_draft_version,
    create_rule_pack,
    delete_rule,
    get_rule_improvements_report,
    get_version_with_rules,
    list_rule_packs,
    list_versions_for_pack,
    nl_edit_version,
    patch_rule,
    publish_version,
    run_test_bench,
)

router = APIRouter(tags=["rules"])


@router.get("/rule-packs", response_model=list[RulePackOut])
async def list_rule_packs_route(db: AsyncSession = Depends(get_org_db)) -> list[RulePack]:
    """specs/04-api-spec.md GET /rule-packs — "starter + org packs"; RLS on rule_packs
    already returns exactly that (global rows + this org's own), nothing else to filter."""
    return await list_rule_packs(db)


@router.post("/rule-packs", response_model=RulePackOut, status_code=201)
async def create_rule_pack_route(
    payload: RulePackCreate,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> RulePack:
    return await create_rule_pack(db, membership.org_id, membership.user_id, payload)


@router.get("/rule-packs/{rule_pack_id}/versions", response_model=list[RuleSetVersionOut])
async def list_rule_pack_versions_route(rule_pack_id: str, db: AsyncSession = Depends(get_org_db)) -> list[RuleSetVersion]:
    return await list_versions_for_pack(db, rule_pack_id)


@router.post("/rule-packs/{rule_pack_id}/versions", response_model=RuleSetVersionOut, status_code=201)
async def create_rule_pack_version_route(
    rule_pack_id: str,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> RuleSetVersion:
    return await create_draft_version(db, membership.org_id, membership.user_id, rule_pack_id)


@router.get("/rule-set-versions/{version_id}", response_model=RuleSetVersionOut)
async def get_rule_set_version_route(version_id: str, db: AsyncSession = Depends(get_org_db)) -> RuleSetVersion:
    version, _rules = await get_version_with_rules(db, version_id)
    return version


@router.get("/rule-set-versions/{version_id}/rules", response_model=list[RuleOut])
async def list_rule_set_version_rules_route(version_id: str, db: AsyncSession = Depends(get_org_db)) -> list[Rule]:
    _version, rules = await get_version_with_rules(db, version_id)
    return rules


@router.post("/rule-set-versions/{version_id}/rules", response_model=RuleOut, status_code=201)
async def create_rule_route(
    version_id: str,
    payload: RuleCreate,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> Rule:
    """specs/04-api-spec.md: "create/edit rules while draft" — if `version_id` refers to
    a published/archived version, this transparently forks a new draft first
    (specs/06: "publish is immutable (edit attempt creates new draft)")."""
    return await add_rule(db, membership.org_id, membership.user_id, version_id, payload)


@router.patch("/rules/{rule_id}", response_model=RuleOut)
async def patch_rule_route(
    rule_id: str,
    payload: RulePatch,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> Rule:
    return await patch_rule(db, membership.org_id, membership.user_id, rule_id, payload)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule_route(
    rule_id: str,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> None:
    await delete_rule(db, membership.org_id, membership.user_id, rule_id)


@router.post("/rule-set-versions/{version_id}/nl-edit", response_model=NlEditResponse)
async def nl_edit_rule_set_version_route(
    version_id: str,
    payload: NlEditRequest,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> NlEditResponse:
    """specs/04-api-spec.md POST /rule-set-versions/{id}/nl-edit — proposals are
    ephemeral (never persisted); confirm an accepted one via the existing
    POST .../rules or PATCH /rules/{id} endpoints."""
    proposals, prompt_version = await nl_edit_version(db, membership.org_id, membership.user_id, version_id, payload.instruction)
    return NlEditResponse(
        prompt_version=prompt_version, instruction=payload.instruction,
        proposals=[
            ProposedRuleChangeOut(
                action=p.action, rule_key=p.rule_key, name=p.name, trigger_type=p.trigger_type,
                config=p.config, exemption_code=p.exemption_code, exclusions=p.exclusions,
                rationale=p.rationale, is_valid=p.is_valid, invalid_reason=p.invalid_reason,
            )
            for p in proposals
        ],
    )


@router.post("/rule-set-versions/{version_id}/test", response_model=TestBenchResponse)
async def test_rule_set_version_route(
    version_id: str,
    payload: TestBenchRequest,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> TestBenchResponse:
    """specs/06-exemption-taxonomy.md § Test bench: "run draft version against selected
    sample documents; show would-be candidates + diff vs current published version."
    Read-only/diagnostic — never creates real candidates."""
    result = await run_test_bench(db, membership.org_id, membership.user_id, version_id, payload.document_ids)
    return TestBenchResponse(**result)


@router.post("/rule-set-versions/{version_id}/publish", response_model=RuleSetVersionOut)
async def publish_rule_set_version_route(
    version_id: str,
    payload: PublishVersionRequest,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> RuleSetVersion:
    return await publish_version(db, membership.org_id, membership.user_id, version_id, payload.changelog)


@router.get("/rule-improvements-report", response_model=RuleImprovementsReportOut)
async def get_rule_improvements_report_route(
    membership: Membership = Depends(require_role("agency_admin", "supervisor")),
    db: AsyncSession = Depends(get_org_db),
) -> RuleImprovementsReportOut:
    """specs/01-product-spec.md US-11 / specs/05-redaction-pipeline.md: rejected AI
    candidates by rule + reviewer-added manual redactions clustered by text pattern —
    report only, never mutates a rule."""
    return RuleImprovementsReportOut(**await get_rule_improvements_report(db, membership.org_id))
