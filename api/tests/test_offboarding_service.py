"""app/services/offboarding_service.py. offboard_org/get_destruction_attestation_facts
manage their own sessions (system_session for the cross-tenant org lookup, org_session
for the writes) — same self-managed-session pattern as app/services/platform_service.py
— so they go through app/db/session.py's module-level AsyncSessionLocal singleton,
which conftest.py's autouse _point_app_db_at_test_database fixture points at the test
database. generate_offboarding_package/find_documents_eligible_for_offboarding_purge
take a session directly and are tested against db_session.
"""

import zipfile
from datetime import UTC, datetime
from io import BytesIO

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, ConflictError, NotFoundError
from app.core.ids import new_id
from app.models.document import Document
from app.models.organization import Organization
from app.services.offboarding_service import (
    find_documents_eligible_for_offboarding_purge,
    generate_destruction_attestation_pdf,
    generate_offboarding_package,
    get_destruction_attestation_facts,
    offboard_org,
)
from app.storage import get_store
from tests.conftest import set_org

PLATFORM_ADMIN_USER_ID = "usr_offboarding_admin"
NOW = datetime(2026, 8, 15, tzinfo=UTC)


async def _create_org(session: AsyncSession, org_id: str, slug: str | None = None) -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :slug, 'WA', 'other', 'starter', 'active', '{}')"
        ),
        {"id": org_id, "slug": slug or org_id},
    )
    await session.execute(
        text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
        {"id": f"usr_{org_id}", "email": f"{org_id}@example.com"},
    )


async def _create_document(
    session: AsyncSession, org_id: str, doc_id: str, *, status: str = "ready_for_review",
    legal_hold: bool = False, request_id: str | None = None, with_original: bool = True,
) -> None:
    original_key = f"originals/{doc_id}"
    if with_original:
        get_store().put(org_id, original_key, b"%PDF-original-bytes")
    await session.execute(
        text(
            "INSERT INTO documents (id, org_id, filename, mime_type, source, status, uploaded_by, "
            "content_sha256, s3_key_original, legal_hold, request_id) VALUES "
            "(:id, :org_id, 'sample.pdf', 'application/pdf', 'upload', :status, :user_id, "
            "'deadbeef', :s3_key, :legal_hold, :request_id)"
        ),
        {
            "id": doc_id, "org_id": org_id, "status": status, "user_id": f"usr_{org_id}",
            "s3_key": original_key if with_original else None, "legal_hold": legal_hold, "request_id": request_id,
        },
    )
    await session.execute(
        text("INSERT INTO manifests (id, doc_id, org_id, version, schema_version, completeness) VALUES "
             "(:id, :doc_id, :org_id, 1, 1, '{}')"),
        {"id": new_id("man"), "doc_id": doc_id, "org_id": org_id},
    )


@pytest.mark.asyncio
async def test_generate_offboarding_package_includes_originals_manifests_and_audit_csv(db_session: AsyncSession) -> None:
    org_id, doc_id = "org_offboard_pkg", "doc_offboard_pkg"
    async with db_session.begin():
        await _create_org(db_session, org_id)
        await _create_document(db_session, org_id, doc_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        package = await generate_offboarding_package(db_session, org_id)

    with zipfile.ZipFile(BytesIO(package)) as zf:
        names = zf.namelist()
        assert f"originals/{doc_id}/sample.pdf" in names
        assert f"manifests/{doc_id}.json" in names
        assert "audit.csv" in names


@pytest.mark.asyncio
async def test_find_documents_eligible_for_offboarding_purge_ignores_status_but_respects_legal_hold(
    db_session: AsyncSession,
) -> None:
    org_id = "org_offboard_eligibility"
    async with db_session.begin():
        await _create_org(db_session, org_id)
        await _create_document(db_session, org_id, "doc_unreviewed", status="ready_for_review")
        await _create_document(db_session, org_id, "doc_exported", status="exported")
        await _create_document(db_session, org_id, "doc_held", status="exported", legal_hold=True)

    async with db_session.begin():
        await set_org(db_session, org_id)
        eligible = await find_documents_eligible_for_offboarding_purge(db_session, org_id)

    assert set(eligible) == {"doc_unreviewed", "doc_exported"}


@pytest.mark.asyncio
async def test_offboard_org_purges_documents_generates_package_and_cancels_plan(db_session: AsyncSession) -> None:
    org_id, doc_id = "org_offboard_full", "doc_offboard_full"
    async with db_session.begin():
        await _create_org(db_session, org_id, slug="acme-county")
        await _create_document(db_session, org_id, doc_id)

    package, purged_count = await offboard_org(PLATFORM_ADMIN_USER_ID, org_id, "acme-county", NOW)

    assert purged_count == 1
    with zipfile.ZipFile(BytesIO(package)) as zf:
        assert f"manifests/{doc_id}.json" in zf.namelist()

    async with db_session.begin():
        await set_org(db_session, org_id)
        org = await db_session.get(Organization, org_id)
        document = await db_session.get(Document, doc_id)
        assert org is not None and org.plan_status == "canceled"
        assert document is not None
        assert document.deleted_at is not None
        assert document.s3_key_original is None


@pytest.mark.asyncio
async def test_offboard_org_respects_legal_hold(db_session: AsyncSession) -> None:
    org_id, doc_id = "org_offboard_held", "doc_offboard_held"
    async with db_session.begin():
        await _create_org(db_session, org_id, slug="held-county")
        await _create_document(db_session, org_id, doc_id, legal_hold=True)

    _package, purged_count = await offboard_org(PLATFORM_ADMIN_USER_ID, org_id, "held-county", NOW)
    assert purged_count == 0

    async with db_session.begin():
        await set_org(db_session, org_id)
        document = await db_session.get(Document, doc_id)
        assert document is not None
        assert document.deleted_at is None


@pytest.mark.asyncio
async def test_offboard_org_rejects_mismatched_confirm_slug(db_session: AsyncSession) -> None:
    org_id = "org_offboard_badslug"
    async with db_session.begin():
        await _create_org(db_session, org_id, slug="right-slug")

    with pytest.raises(ApiError) as exc_info:
        await offboard_org(PLATFORM_ADMIN_USER_ID, org_id, "wrong-slug", NOW)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_offboard_org_rejects_a_missing_org() -> None:
    with pytest.raises(NotFoundError):
        await offboard_org(PLATFORM_ADMIN_USER_ID, "org_does_not_exist", "whatever", NOW)


@pytest.mark.asyncio
async def test_offboard_org_rejects_a_second_offboard(db_session: AsyncSession) -> None:
    org_id = "org_offboard_twice"
    async with db_session.begin():
        await _create_org(db_session, org_id, slug="twice-slug")

    await offboard_org(PLATFORM_ADMIN_USER_ID, org_id, "twice-slug", NOW)
    with pytest.raises(ConflictError):
        await offboard_org(PLATFORM_ADMIN_USER_ID, org_id, "twice-slug", NOW)


@pytest.mark.asyncio
async def test_destruction_attestation_facts_and_pdf_after_offboarding(db_session: AsyncSession) -> None:
    org_id, doc_id = "org_offboard_attest", "doc_offboard_attest"
    async with db_session.begin():
        await _create_org(db_session, org_id, slug="attest-slug")
        await _create_document(db_session, org_id, doc_id)

    await offboard_org(PLATFORM_ADMIN_USER_ID, org_id, "attest-slug", NOW)

    facts = await get_destruction_attestation_facts(org_id)
    assert facts.org_id == org_id
    assert facts.documents_purged == 1

    pdf_bytes = generate_destruction_attestation_pdf(facts)
    assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_destruction_attestation_facts_raise_before_offboarding(db_session: AsyncSession) -> None:
    org_id = "org_offboard_not_yet"
    async with db_session.begin():
        await _create_org(db_session, org_id, slug="not-yet-slug")

    with pytest.raises(NotFoundError):
        await get_destruction_attestation_facts(org_id)
