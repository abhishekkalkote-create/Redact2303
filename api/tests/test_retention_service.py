"""app/services/retention_service.py. All functions here take a session directly, so
they're tested against the real test database via db_session — same as
app/services/usage_service.py's functions."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.models.document import Document
from app.models.organization import Organization
from app.services.retention_service import (
    find_documents_eligible_for_purge,
    generate_deletion_certificate_pdf,
    get_deletion_certificate_facts,
    purge_document_content,
    run_retention_sweep,
)
from app.storage import get_store
from tests.conftest import set_org

NOW = datetime(2026, 8, 15, tzinfo=UTC)


async def _create_org(session: AsyncSession, org_id: str, *, retention_days_uploads: int = 90) -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'other', 'starter', 'active', :settings)"
        ),
        {"id": org_id, "settings": f'{{"retention_days_uploads": {retention_days_uploads}}}'},
    )
    await session.execute(
        text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
        {"id": f"usr_{org_id}", "email": f"{org_id}@example.com"},
    )


async def _create_exported_document(
    session: AsyncSession, org_id: str, doc_id: str, *, exported_days_ago: int, legal_hold: bool = False,
    request_id: str | None = None,
) -> tuple[str, str]:
    original_key = f"originals/{doc_id}"
    get_store().put(org_id, original_key, b"%PDF-original-bytes")
    preview_key = f"previews/{doc_id}/1.png"
    get_store().put(org_id, preview_key, b"fake-png-bytes")

    await session.execute(
        text(
            "INSERT INTO documents (id, org_id, filename, mime_type, source, status, uploaded_by, "
            "content_sha256, s3_key_original, legal_hold, request_id) VALUES "
            "(:id, :org_id, 'sample.pdf', 'application/pdf', 'upload', 'exported', :user_id, "
            "'deadbeef', :s3_key, :legal_hold, :request_id)"
        ),
        {
            "id": doc_id, "org_id": org_id, "user_id": f"usr_{org_id}", "s3_key": original_key,
            "legal_hold": legal_hold, "request_id": request_id,
        },
    )
    await session.execute(
        text(
            "INSERT INTO document_pages (id, doc_id, org_id, page_no, s3_key_preview) VALUES "
            "(:id, :doc_id, :org_id, 1, :s3_key)"
        ),
        {"id": new_id("pg"), "doc_id": doc_id, "org_id": org_id, "s3_key": preview_key},
    )
    exported_at = NOW - timedelta(days=exported_days_ago)
    await session.execute(
        text(
            "INSERT INTO export_artifacts (id, org_id, doc_id, type, s3_key, sha256, manifest_version, "
            "integrity_check, created_by, created_at) VALUES "
            "(:id, :org_id, :doc_id, 'clean_pdf', :s3_key, 'exportsha', 1, '{}', :user_id, :created_at)"
        ),
        {
            "id": new_id("exp"), "org_id": org_id, "doc_id": doc_id, "s3_key": f"exports/{doc_id}.pdf",
            "user_id": f"usr_{org_id}", "created_at": exported_at,
        },
    )
    return original_key, preview_key


@pytest.mark.asyncio
async def test_find_documents_eligible_for_purge_respects_retention_window(db_session: AsyncSession) -> None:
    org_id = "org_retention_a"
    async with db_session.begin():
        await _create_org(db_session, org_id, retention_days_uploads=90)
        await _create_exported_document(db_session, org_id, "doc_old", exported_days_ago=100)
        await _create_exported_document(db_session, org_id, "doc_recent", exported_days_ago=10)

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        eligible = await find_documents_eligible_for_purge(db_session, org, NOW)

    assert eligible == ["doc_old"]


@pytest.mark.asyncio
async def test_find_documents_eligible_for_purge_respects_document_legal_hold(db_session: AsyncSession) -> None:
    org_id = "org_retention_b"
    async with db_session.begin():
        await _create_org(db_session, org_id)
        await _create_exported_document(db_session, org_id, "doc_held", exported_days_ago=100, legal_hold=True)

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        eligible = await find_documents_eligible_for_purge(db_session, org, NOW)

    assert eligible == []


@pytest.mark.asyncio
async def test_find_documents_eligible_for_purge_respects_request_legal_hold(db_session: AsyncSession) -> None:
    org_id = "org_retention_c"
    async with db_session.begin():
        await _create_org(db_session, org_id)
        await db_session.execute(
            text(
                "INSERT INTO requests (id, org_id, title, status, legal_hold) VALUES "
                "(:id, :org_id, 'Held request', 'open', true)"
            ),
            {"id": "req_held", "org_id": org_id},
        )
        await _create_exported_document(db_session, org_id, "doc_in_held_request", exported_days_ago=100, request_id="req_held")

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        eligible = await find_documents_eligible_for_purge(db_session, org, NOW)

    assert eligible == []


@pytest.mark.asyncio
async def test_purge_document_content_deletes_storage_and_nulls_columns(db_session: AsyncSession) -> None:
    org_id, doc_id = "org_retention_d", "doc_to_purge"
    async with db_session.begin():
        await _create_org(db_session, org_id)
        original_key, preview_key = await _create_exported_document(db_session, org_id, doc_id, exported_days_ago=100)

    store = get_store()
    assert store.exists(org_id, original_key)
    assert store.exists(org_id, preview_key)

    async with db_session.begin():
        await set_org(db_session, org_id)
        await purge_document_content(db_session, org_id, doc_id, NOW)

    assert not store.exists(org_id, original_key)
    assert not store.exists(org_id, preview_key)

    async with db_session.begin():
        await set_org(db_session, org_id)
        document = await db_session.get(Document, doc_id)
        assert document is not None
        assert document.s3_key_original is None
        assert document.content_sha256 is None
        assert document.deleted_at == NOW


@pytest.mark.asyncio
async def test_run_retention_sweep_purges_only_eligible_documents(db_session: AsyncSession) -> None:
    org_id = "org_retention_e"
    async with db_session.begin():
        await _create_org(db_session, org_id)
        await _create_exported_document(db_session, org_id, "doc_e_old", exported_days_ago=100)
        await _create_exported_document(db_session, org_id, "doc_e_recent", exported_days_ago=5)

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        purged_count = await run_retention_sweep(db_session, org, NOW)

    assert purged_count == 1

    async with db_session.begin():
        await set_org(db_session, org_id)
        old_doc = await db_session.get(Document, "doc_e_old")
        recent_doc = await db_session.get(Document, "doc_e_recent")
        assert old_doc is not None and old_doc.deleted_at is not None
        assert recent_doc is not None and recent_doc.deleted_at is None


@pytest.mark.asyncio
async def test_run_retention_sweep_is_idempotent(db_session: AsyncSession) -> None:
    org_id = "org_retention_f"
    async with db_session.begin():
        await _create_org(db_session, org_id)
        await _create_exported_document(db_session, org_id, "doc_f", exported_days_ago=100)

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        first_run = await run_retention_sweep(db_session, org, NOW)
    assert first_run == 1

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        assert org is not None
        second_run = await run_retention_sweep(db_session, org, NOW + timedelta(days=1))
    assert second_run == 0


@pytest.mark.asyncio
async def test_get_deletion_certificate_facts_and_pdf(db_session: AsyncSession) -> None:
    org_id, doc_id = "org_retention_g", "doc_g"
    async with db_session.begin():
        await _create_org(db_session, org_id)
        await _create_exported_document(db_session, org_id, doc_id, exported_days_ago=100)

    async with db_session.begin():
        await set_org(db_session, org_id)
        await purge_document_content(db_session, org_id, doc_id, NOW)

    async with db_session.begin():
        await set_org(db_session, org_id)
        facts = await get_deletion_certificate_facts(db_session, org_id, doc_id)

    assert facts.doc_id == doc_id
    assert facts.filename == "sample.pdf"
    assert facts.sha256_at_purge == "deadbeef"

    pdf_bytes = generate_deletion_certificate_pdf(facts)
    assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_get_deletion_certificate_facts_raises_if_never_purged(db_session: AsyncSession) -> None:
    org_id, doc_id = "org_retention_h", "doc_h"
    async with db_session.begin():
        await _create_org(db_session, org_id)
        await _create_exported_document(db_session, org_id, doc_id, exported_days_ago=5)

    async with db_session.begin():
        await set_org(db_session, org_id)
        with pytest.raises(NotFoundError):
            await get_deletion_certificate_facts(db_session, org_id, doc_id)
