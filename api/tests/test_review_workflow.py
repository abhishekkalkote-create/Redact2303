"""Phase 3 AC (specs/10-build-plan.md): "dual-approval org cannot export without
supervisor action (API-enforced)." Exercises the full status-machine path against a real
Postgres: complete_review branches on org.settings.dual_approval_required, and the
resulting awaiting_approval status is a hard block on export_service.create_export until
approve_document runs. require_role's role check is unit-tested directly (it's a plain
dependency closure — calling it outside FastAPI's DI just uses the passed argument)."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_role
from app.core.errors import ApiError
from app.core.ids import new_id
from app.models.document import Document, DocumentPage
from app.models.membership import Membership
from app.services.export_service import create_export
from app.services.review_service import approve_document, complete_review, return_document
from tests.conftest import set_org


async def _seed_org_user_doc(session: AsyncSession, org_id: str, user_id: str, doc_id: str, *, dual_approval: bool) -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'other', 'pilot', 'trialing', :settings)"
        ),
        {"id": org_id, "settings": f'{{"dual_approval_required": {"true" if dual_approval else "false"}}}'},
    )
    await session.execute(
        text(
            "INSERT INTO users (id, email, name, status) VALUES "
            "(:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )
    session.add(
        Document(
            id=doc_id, org_id=org_id, filename="sample.pdf", mime_type="application/pdf",
            source="upload", status="ready_for_review", uploaded_by=user_id,
            content_sha256="deadbeef",
        )
    )


@pytest.mark.asyncio
async def test_complete_review_without_dual_approval_goes_straight_to_review_complete(db_session: AsyncSession) -> None:
    org_id, user_id, doc_id = "org_rw_1", "usr_rw_1", new_id("doc")
    async with db_session.begin():
        await _seed_org_user_doc(db_session, org_id, user_id, doc_id, dual_approval=False)

    async with db_session.begin():
        await set_org(db_session, org_id)
        document = await complete_review(db_session, org_id, doc_id, user_id)
        assert document.status == "review_complete"


@pytest.mark.asyncio
async def test_complete_review_with_dual_approval_lands_in_awaiting_approval(db_session: AsyncSession) -> None:
    org_id, user_id, doc_id = "org_rw_2", "usr_rw_2", new_id("doc")
    async with db_session.begin():
        await _seed_org_user_doc(db_session, org_id, user_id, doc_id, dual_approval=True)

    async with db_session.begin():
        await set_org(db_session, org_id)
        document = await complete_review(db_session, org_id, doc_id, user_id)
        assert document.status == "awaiting_approval"

    async with db_session.begin():
        await set_org(db_session, org_id)
        with pytest.raises(ApiError) as exc_info:
            await create_export(db_session, org_id, doc_id, user_id)
        assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_approve_document_unblocks_export_gate(db_session: AsyncSession) -> None:
    org_id, user_id, doc_id = "org_rw_3", "usr_rw_3", new_id("doc")
    async with db_session.begin():
        await _seed_org_user_doc(db_session, org_id, user_id, doc_id, dual_approval=True)

    async with db_session.begin():
        await set_org(db_session, org_id)
        await complete_review(db_session, org_id, doc_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        document = await approve_document(db_session, org_id, doc_id, user_id, note="looks good")
        assert document.status == "review_complete"

    # export_service still needs a manifest to get past its own lookup — absence of the
    # earlier "must be review_complete" 422 is exactly what this test is verifying.
    async with db_session.begin():
        await set_org(db_session, org_id)
        with pytest.raises(ApiError) as exc_info:
            await create_export(db_session, org_id, doc_id, user_id)
        assert exc_info.value.status_code == 404, "should fail on missing manifest, not the status gate"


@pytest.mark.asyncio
async def test_return_document_sends_back_to_in_review(db_session: AsyncSession) -> None:
    org_id, user_id, doc_id = "org_rw_4", "usr_rw_4", new_id("doc")
    async with db_session.begin():
        await _seed_org_user_doc(db_session, org_id, user_id, doc_id, dual_approval=True)

    async with db_session.begin():
        await set_org(db_session, org_id)
        await complete_review(db_session, org_id, doc_id, user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        document = await return_document(db_session, org_id, doc_id, user_id, note="missing a redaction")
        assert document.status == "in_review"


@pytest.mark.asyncio
async def test_approve_document_rejects_wrong_status(db_session: AsyncSession) -> None:
    org_id, user_id, doc_id = "org_rw_5", "usr_rw_5", new_id("doc")
    async with db_session.begin():
        await _seed_org_user_doc(db_session, org_id, user_id, doc_id, dual_approval=False)

    async with db_session.begin():
        await set_org(db_session, org_id)
        with pytest.raises(ApiError) as exc_info:
            await approve_document(db_session, org_id, doc_id, user_id, note=None)
        assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_complete_review_blocks_on_low_ocr_confidence_page(db_session: AsyncSession) -> None:
    org_id, user_id, doc_id = "org_rw_6", "usr_rw_6", new_id("doc")
    async with db_session.begin():
        await _seed_org_user_doc(db_session, org_id, user_id, doc_id, dual_approval=False)
        db_session.add(
            DocumentPage(doc_id=doc_id, org_id=org_id, page_no=1, has_text_layer=True, ocr_confidence=0.42)
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        with pytest.raises(ApiError) as exc_info:
            await complete_review(db_session, org_id, doc_id, user_id)
        assert exc_info.value.status_code == 422
        assert "low-confidence OCR" in exc_info.value.detail
        assert "1" in exc_info.value.detail


@pytest.mark.asyncio
async def test_complete_review_allows_good_ocr_and_born_digital_pages(db_session: AsyncSession) -> None:
    org_id, user_id, doc_id = "org_rw_7", "usr_rw_7", new_id("doc")
    async with db_session.begin():
        await _seed_org_user_doc(db_session, org_id, user_id, doc_id, dual_approval=False)
        db_session.add_all(
            [
                DocumentPage(doc_id=doc_id, org_id=org_id, page_no=1, has_text_layer=True, ocr_confidence=0.91),
                DocumentPage(doc_id=doc_id, org_id=org_id, page_no=2, has_text_layer=True, ocr_confidence=None),
            ]
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        document = await complete_review(db_session, org_id, doc_id, user_id)
        assert document.status == "review_complete"


@pytest.mark.asyncio
async def test_require_role_blocks_reviewer_and_allows_supervisor() -> None:
    dep = require_role("agency_admin", "supervisor")
    reviewer = Membership(id="mem_1", org_id="org_x", user_id="usr_1", role="reviewer", status="active")
    supervisor = Membership(id="mem_2", org_id="org_x", user_id="usr_2", role="supervisor", status="active")

    with pytest.raises(ApiError) as exc_info:
        await dep(membership=reviewer)
    assert exc_info.value.status_code == 403

    allowed = await dep(membership=supervisor)
    assert allowed is supervisor
