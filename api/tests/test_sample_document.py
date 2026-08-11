"""app/pipeline/sample_document.py + app/pipeline/run.py's process_document(bill_usage=).
Full pipeline integration against a real document, through the real process_document
orchestrator, against a real Postgres test DB — same shape as
test_pipeline_integration.py. No LLM call needed here: the sample document is
deliberately built to trigger deterministic (Presidio/regex) rules alone."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.models.document import Document
from app.pipeline.run import process_document
from app.pipeline.sample_document import generate_sample_document_pdf
from app.services.exemption_service import clone_library_for_org
from app.storage import get_store
from tests.conftest import set_org


async def _seed_org_user_and_sample_document(session: AsyncSession, org_id: str, user_id: str, doc_id: str) -> None:
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
        text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )
    await clone_library_for_org(session, org_id, "WA")

    original_key = f"originals/{doc_id}"
    get_store().put(org_id, original_key, generate_sample_document_pdf())
    session.add(
        Document(
            id=doc_id, org_id=org_id, filename="sample-incident-report.pdf", mime_type="application/pdf",
            source="sample", status="uploaded", uploaded_by=user_id, s3_key_original=original_key,
            content_sha256="deadbeef",
        )
    )


@pytest.mark.asyncio
async def test_sample_document_triggers_multiple_exemption_codes(db_session: AsyncSession) -> None:
    org_id, user_id, doc_id = "org_sample_a", "usr_sample_a", new_id("doc")
    async with db_session.begin():
        await _seed_org_user_and_sample_document(db_session, org_id, user_id, doc_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        manifest = await process_document(db_session, org_id, doc_id, actor_id=user_id, bill_usage=False)
        assert manifest.doc_id == doc_id

    async with db_session.begin():
        await set_org(db_session, org_id)
        result = await db_session.execute(
            text(
                "SELECT rc.display_text_encrypted, ec.code FROM redaction_candidates rc "
                "LEFT JOIN exemption_codes ec ON ec.id = rc.exemption_code_id WHERE rc.doc_id = :doc_id"
            ),
            {"doc_id": doc_id},
        )
        rows = result.all()

    cipher = get_cipher()
    codes_found = {row.code for row in rows if row.code}
    texts_found = {cipher.decrypt(org_id, row.display_text_encrypted) for row in rows}

    # Core PII (SSN/phone/email) -> b(6); Public Safety (CI code, case number) -> 7(D)/7(A).
    assert {"b(6)", "7(D)", "7(A)"} <= codes_found, f"expected multiple exemption codes, got {codes_found}"
    assert "123-45-6789" in texts_found
    assert "CI-4471" in texts_found


@pytest.mark.asyncio
async def test_sample_document_processing_is_never_billed(db_session: AsyncSession) -> None:
    org_id, user_id, doc_id = "org_sample_b", "usr_sample_b", new_id("doc")
    async with db_session.begin():
        await _seed_org_user_and_sample_document(db_session, org_id, user_id, doc_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        await process_document(db_session, org_id, doc_id, actor_id=user_id, bill_usage=False)

    async with db_session.begin():
        await set_org(db_session, org_id)
        count = (await db_session.execute(text("SELECT count(*) FROM usage_records WHERE doc_id = :id"), {"id": doc_id})).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_a_real_document_is_billed_by_contrast(db_session: AsyncSession) -> None:
    """Same pipeline, bill_usage left at its default (True) — proves the sample-only
    exemption is deliberate, not just an accident of the pipeline never billing."""
    org_id, user_id, doc_id = "org_sample_c", "usr_sample_c", new_id("doc")
    async with db_session.begin():
        await _seed_org_user_and_sample_document(db_session, org_id, user_id, doc_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        await process_document(db_session, org_id, doc_id, actor_id=user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        count = (
            await db_session.execute(
                text("SELECT count(*) FROM usage_records WHERE doc_id = :id AND metric = 'pages_processed'"), {"id": doc_id}
            )
        ).scalar_one()
    assert count == 1
