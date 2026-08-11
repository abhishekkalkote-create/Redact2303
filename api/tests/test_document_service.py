"""app/services/document_service.py's get_manifest_data — extracted from
app/routers/documents.py's GET /documents/{id}/manifest (slice 8) so
app/services/offboarding_service.py's export package can reuse the exact same
decrypt-and-shape logic. Behavior itself predates this test; this covers the shared
function directly."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.services.document_service import get_manifest_data
from tests.conftest import set_org


async def _seed_document_with_manifest_and_candidate(session: AsyncSession, org_id: str, doc_id: str) -> None:
    await set_org(session, org_id)
    user_id = f"usr_{org_id}"
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'other', 'starter', 'active', '{}')"
        ),
        {"id": org_id},
    )
    await session.execute(
        text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )
    await session.execute(
        text(
            "INSERT INTO documents (id, org_id, filename, mime_type, source, status, uploaded_by, content_sha256) "
            "VALUES (:id, :org_id, 'sample.pdf', 'application/pdf', 'upload', 'ready_for_review', :user_id, 'deadbeef')"
        ),
        {"id": doc_id, "org_id": org_id, "user_id": user_id},
    )
    await session.execute(
        text("INSERT INTO manifests (id, doc_id, org_id, version, schema_version, completeness) VALUES "
             "(:id, :doc_id, :org_id, 1, 1, '{}')"),
        {"id": new_id("man"), "doc_id": doc_id, "org_id": org_id},
    )
    exc_id = new_id("exc")
    await session.execute(
        text("INSERT INTO exemption_codes (id, org_id, code, label, status) VALUES (:id, :org_id, 'b6', 'Personal privacy', 'active')"),
        {"id": exc_id, "org_id": org_id},
    )
    cipher = get_cipher()
    await session.execute(
        text(
            "INSERT INTO redaction_candidates (id, org_id, doc_id, page_no, bbox, display_text_encrypted, "
            "origin, exemption_code_id, confidence, state, detector_versions) VALUES "
            "(:id, :org_id, :doc_id, 1, '{}', :text, 'manual', :exc_id, 'n/a-manual', 'approved', '{}')"
        ),
        {"id": new_id("cand"), "org_id": org_id, "doc_id": doc_id, "text": cipher.encrypt(org_id, "Jane Doe"), "exc_id": exc_id},
    )


@pytest.mark.asyncio
async def test_get_manifest_data_decrypts_candidate_text_and_resolves_exemption_code(db_session: AsyncSession) -> None:
    org_id, doc_id = "org_manifest_a", "doc_manifest_a"
    async with db_session.begin():
        await _seed_document_with_manifest_and_candidate(db_session, org_id, doc_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        data = await get_manifest_data(db_session, doc_id)

    assert data["doc_id"] == doc_id
    assert data["version"] == 1
    assert len(data["candidates"]) == 1
    candidate = data["candidates"][0]
    assert candidate["display_text"] == "Jane Doe"
    assert candidate["exemption_code"] == "b6"
    assert candidate["state"] == "approved"


@pytest.mark.asyncio
async def test_get_manifest_data_raises_not_found_without_a_manifest(db_session: AsyncSession) -> None:
    org_id = "org_manifest_b"
    async with db_session.begin():
        await set_org(db_session, org_id)
        with pytest.raises(NotFoundError):
            await get_manifest_data(db_session, "doc_never_processed")
