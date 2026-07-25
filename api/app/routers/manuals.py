from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_org_db, require_role
from app.models.manual import DraftRule, Manual
from app.models.membership import Membership
from app.schemas.manual import (
    DraftRuleAcceptRequest,
    DraftRuleOut,
    DraftRuleRejectRequest,
    ManualOut,
)
from app.schemas.rule import RuleOut
from app.services.manual_service import (
    accept_draft_rule,
    list_draft_rules,
    list_manuals,
    reject_draft_rule,
    upload_manual,
)

router = APIRouter(tags=["manuals"])


@router.get("/manuals", response_model=list[ManualOut])
async def list_manuals_route(
    _membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> list[Manual]:
    return await list_manuals(db)


@router.post("/manuals", response_model=ManualOut, status_code=201)
async def upload_manual_route(
    file: UploadFile,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> Manual:
    """specs/04-api-spec.md POST /manuals — "upload manual → extraction job." Runs
    synchronously (same Phase 1 simplification as document processing); by the time this
    responds, GET .../draft-rules already has results (or the manual's extraction_status
    is "failed" with `error` set)."""
    data = await file.read()
    return await upload_manual(db, membership.org_id, membership.user_id, file.filename or "manual.pdf", data)


@router.get("/manuals/{manual_id}/draft-rules", response_model=list[DraftRuleOut])
async def list_manual_draft_rules_route(
    manual_id: str,
    _membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> list[DraftRule]:
    return await list_draft_rules(db, manual_id)


@router.post("/draft-rules/{draft_rule_id}:accept", response_model=RuleOut)
async def accept_draft_rule_route(
    draft_rule_id: str,
    payload: DraftRuleAcceptRequest,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
):
    """specs/06-exemption-taxonomy.md: "accepted drafts land in a new draft rule set
    version" — via the existing rule CRUD (auto-forks a draft if the target version is
    published)."""
    return await accept_draft_rule(db, membership.org_id, membership.user_id, draft_rule_id, payload)


@router.post("/draft-rules/{draft_rule_id}:reject", response_model=DraftRuleOut)
async def reject_draft_rule_route(
    draft_rule_id: str,
    payload: DraftRuleRejectRequest,
    membership: Membership = Depends(require_role("agency_admin")),
    db: AsyncSession = Depends(get_org_db),
) -> DraftRule:
    return await reject_draft_rule(db, membership.org_id, membership.user_id, draft_rule_id, payload.note)
