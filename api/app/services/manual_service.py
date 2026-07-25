"""specs/06-exemption-taxonomy.md § Manual-to-rule extraction. Runs synchronously in the
API process, same Phase 1 simplification as app/pipeline/run.py (real async workers are
a later, infra-dependent change, not a code-shape change) — upload triggers extraction
immediately rather than a separately-polled job.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, NotFoundError
from app.core.ids import new_id
from app.llm.provider import get_provider
from app.models.exemption_code import ExemptionCode
from app.models.manual import DraftRule, Manual
from app.pipeline.extract import extract_pdf
from app.pipeline.intake import content_sha256, validate_and_scan
from app.pipeline.manual_extraction import run_extraction_for_page
from app.schemas.manual import DraftRuleAcceptRequest
from app.schemas.rule import RuleCreate
from app.services.audit_service import write_audit_event
from app.services.rule_service import add_rule
from app.storage import get_store


async def upload_manual(session: AsyncSession, org_id: str, user_id: str, filename: str, data: bytes) -> Manual:
    validate_and_scan(data)  # same PDF-only + malware-scan gate as document intake; raises IntakeError (422) on failure
    manual_id = new_id("mnl")
    s3_key = f"manuals/{manual_id}"
    get_store().put(org_id, s3_key, data)

    manual = Manual(
        id=manual_id, org_id=org_id, filename=filename, s3_key=s3_key,
        uploaded_by=user_id, extraction_status="pending",
    )
    session.add(manual)
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="manual.uploaded", object_type="manual", object_id=manual.id,
        metadata={"filename": filename, "size_bytes": len(data), "sha256": content_sha256(data)},
    )
    await session.flush()

    try:
        await run_extraction(session, org_id, manual.id)
    except Exception as exc:  # noqa: BLE001 — any extraction failure must land the manual
        # in `failed` with an audit trail, not propagate as an unhandled 500 (matches
        # app/routers/documents.py's upload_document pipeline-failure handling).
        manual.extraction_status = "failed"
        manual.error = str(exc)
        await write_audit_event(
            session, org_id=org_id, actor_type="system", actor_id=user_id,
            action="manual.extraction_failed", object_type="manual", object_id=manual.id,
            metadata={"error": str(exc)},
        )
        await session.flush()

    await session.refresh(manual)
    return manual


async def _exemption_code_id_by_code(session: AsyncSession, org_id: str) -> dict[str, str]:
    result = await session.execute(
        select(ExemptionCode.code, ExemptionCode.id).where(ExemptionCode.org_id == org_id, ExemptionCode.status == "active")
    )
    return {row[0]: row[1] for row in result.all()}


async def run_extraction(session: AsyncSession, org_id: str, manual_id: str) -> Manual:
    manual = await session.get(Manual, manual_id)
    if manual is None:
        raise NotFoundError("Manual not found")

    manual.extraction_status = "processing"
    await session.flush()

    data = get_store().get(org_id, manual.s3_key)
    pages = extract_pdf(data)
    code_id_by_code = await _exemption_code_id_by_code(session, org_id)
    provider = get_provider()

    total_drafts = 0
    for page in pages:
        _section_type, extracted, _in_tok, _out_tok = run_extraction_for_page(
            provider, page.full_text, page.page_no, set(code_id_by_code)
        )
        for draft in extracted:
            session.add(
                DraftRule(
                    id=new_id("drft"), org_id=org_id, manual_id=manual.id, rule_key=None,
                    name=draft.name or "(untitled)", trigger_type=draft.trigger_type or "llm_context",
                    config=draft.config,
                    exemption_code_id=code_id_by_code.get(draft.exemption_code) if draft.exemption_code else None,
                    exclusions=draft.exclusions, scope="org", source_ref=draft.source_ref,
                    ai_notes=(draft.ambiguity_notes or "") + (f" [REJECTED: {draft.invalid_reason}]" if draft.invalid_reason else ""),
                    status="pending",
                )
            )
            total_drafts += 1

    manual.extraction_status = "completed"
    await write_audit_event(
        session, org_id=org_id, actor_type="system", actor_id=manual.uploaded_by,
        action="manual.extraction_completed", object_type="manual", object_id=manual.id,
        metadata={"pages": len(pages), "draft_rules": total_drafts},
    )
    await session.flush()
    await session.refresh(manual)
    return manual


async def list_manuals(session: AsyncSession) -> list[Manual]:
    """RLS already scopes `manuals` to the calling org — no explicit org_id filter needed
    (matches app/services/document_service.list_documents's convention)."""
    result = await session.execute(select(Manual).order_by(Manual.created_at.desc()))
    return list(result.scalars().all())


async def list_draft_rules(session: AsyncSession, manual_id: str) -> list[DraftRule]:
    result = await session.execute(select(DraftRule).where(DraftRule.manual_id == manual_id).order_by(DraftRule.created_at))
    return list(result.scalars().all())


async def accept_draft_rule(session: AsyncSession, org_id: str, user_id: str, draft_rule_id: str, payload: DraftRuleAcceptRequest):
    """specs/06: "accepted drafts land in a new draft rule set version" — reuses
    app/services/rule_service.add_rule, so a published target version transparently
    forks a new draft first, same as any other rule edit."""
    draft = await session.get(DraftRule, draft_rule_id)
    if draft is None:
        raise NotFoundError("Draft rule not found")
    if draft.status != "pending":
        raise ApiError(422, "Unprocessable Entity", f"Draft rule already {draft.status}")

    rule = await add_rule(
        session, org_id, user_id, payload.rule_set_version_id,
        RuleCreate(
            rule_key=payload.rule_key, name=payload.name or draft.name,
            trigger_type=payload.trigger_type or draft.trigger_type,
            config=payload.config or draft.config,
            exemption_code_id=payload.exemption_code_id or draft.exemption_code_id,
            exclusions=payload.exclusions if payload.exclusions is not None else draft.exclusions,
            priority=draft.priority, confidence_policy=draft.confidence_policy,
            scope=draft.scope, source_ref=draft.source_ref,
        ),
    )
    draft.status = "accepted"
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="draft_rule.accepted", object_type="draft_rule", object_id=draft.id,
        metadata={"rule_id": rule.id, "rule_set_version_id": rule.rule_set_version_id},
    )
    await session.flush()
    return rule


async def reject_draft_rule(session: AsyncSession, org_id: str, user_id: str, draft_rule_id: str, note: str | None) -> DraftRule:
    draft = await session.get(DraftRule, draft_rule_id)
    if draft is None:
        raise NotFoundError("Draft rule not found")
    if draft.status != "pending":
        raise ApiError(422, "Unprocessable Entity", f"Draft rule already {draft.status}")

    draft.status = "rejected"
    await write_audit_event(
        session, org_id=org_id, actor_type="user", actor_id=user_id,
        action="draft_rule.rejected", object_type="draft_rule", object_id=draft.id,
        metadata={"note": note},
    )
    await session.flush()
    await session.refresh(draft)
    return draft
