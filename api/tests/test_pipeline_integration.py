"""Full pipeline integration: deterministic (Presidio) + contextual (fake LLM) detection
running together against a real document, through the real process_document orchestrator,
against a real Postgres test DB. Only the LLM call itself is faked — everything else
(extraction, RLS, encryption, merge, DB writes, local content storage) is real."""

import fitz
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.llm.provider import FakeLLMProvider
from app.models.document import Document
from app.services.exemption_service import clone_library_for_org
from app.storage import get_store
from tests.conftest import set_org


def _sample_pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Incident Report - Springfield PD")
    page.insert_text((72, 130), "The victim Jane Doe reported the incident.")
    page.insert_text((72, 160), "Social security number: 234-56-7890.")
    data = doc.tobytes()
    doc.close()
    return data


@pytest.mark.asyncio
async def test_deterministic_and_contextual_detection_run_together(db_session: AsyncSession, monkeypatch) -> None:
    org_id = "org_pipeline_test"
    user_id = "usr_pipeline_test"
    doc_id = new_id("doc")

    original_key = f"originals/{doc_id}"
    get_store().put(org_id, original_key, _sample_pdf_bytes())

    async with db_session.begin():
        await set_org(db_session, org_id)
        await db_session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
                "plan, plan_status, settings) VALUES "
                "(:id, 'Pipeline Test Org', 'pipeline-test-org', 'WA', 'police', 'pilot', 'trialing', '{}')"
            ),
            {"id": org_id},
        )
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, status) VALUES "
                "(:id, 'pipeline-test@example.com', 'Pipeline Test', 'active') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": user_id},
        )
        await clone_library_for_org(db_session, org_id, "WA")

        document = Document(
            id=doc_id, org_id=org_id, filename="sample.pdf", mime_type="application/pdf",
            source="upload", status="uploaded", uploaded_by=user_id, s3_key_original=original_key,
            content_sha256="deadbeef",
        )
        db_session.add(document)

    fake_provider = FakeLLMProvider(
        canned_responses=[
            (
                "Jane Doe",
                (
                    '{"findings": [{"quote": "Jane Doe", "entity_kind": "victim_name", '
                    '"exemption_code": "7(C)", "confidence": 0.9, "justification": "victim identity protection"}]}'
                ),
            ),
        ]
    )
    monkeypatch.setattr("app.pipeline.run.get_provider", lambda: fake_provider)

    from app.pipeline.run import process_document

    async with db_session.begin():
        await set_org(db_session, org_id)
        manifest = await process_document(db_session, org_id, doc_id, actor_id=user_id)
        assert manifest.doc_id == doc_id

    async with db_session.begin():
        await set_org(db_session, org_id)
        result = await db_session.execute(
            text("SELECT id, origin, exemption_code_id, display_text_encrypted FROM redaction_candidates WHERE doc_id = :doc_id"),
            {"doc_id": doc_id},
        )
        rows = result.all()

    cipher = get_cipher()
    decrypted = {cipher.decrypt(org_id, r.display_text_encrypted): r.origin for r in rows}

    assert "234-56-7890" in decrypted, "deterministic SSN detection should have run"
    assert decrypted["234-56-7890"] == "deterministic"
    assert "Jane Doe" in decrypted, "contextual LLM detection should have run (via fake provider)"
    assert decrypted["Jane Doe"] == "llm"

    assert len(fake_provider.calls) >= 1, "the fake provider should actually have been invoked"

    async with db_session.begin():
        await set_org(db_session, org_id)
        doc_result = await db_session.execute(
            text("SELECT status, rule_set_version_ids FROM documents WHERE id = :id"), {"id": doc_id}
        )
        row = doc_result.one()
        assert row.status == "ready_for_review"
        # specs/03-data-model.md: "locked at processing" — all 5 starter packs, since this
        # org never configured settings.default_rule_pack_ids.
        assert row.rule_set_version_ids is not None
        assert len(row.rule_set_version_ids) == 5
