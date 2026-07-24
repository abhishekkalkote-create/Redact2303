"""specs/10-build-plan.md Phase 3 AC: "concurrent reviewers on one document don't
clobber (manifest If-Match verified by test)." Two reviewers who both fetched the
manifest at version 1: the first patch wins and bumps the manifest to version 2; the
second reviewer's stale If-Match is rejected with 409 rather than silently overwriting
the first reviewer's decision. Retrying with the fresh version succeeds."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.ids import new_id
from app.models.document import Document
from app.models.manifest import Manifest
from app.services.review_service import (
    create_manual_candidate,
    get_manifest_by_doc,
    patch_candidate,
)
from tests.conftest import set_org


async def _seed_org_user_doc(session: AsyncSession, org_id: str, user_id: str, doc_id: str) -> str:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'other', 'pilot', 'trialing', '{}')"
        ),
        {"id": org_id},
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
            source="upload", status="ready_for_review", uploaded_by=user_id, content_sha256="deadbeef",
        )
    )
    session.add(Manifest(id=new_id("man"), org_id=org_id, doc_id=doc_id, version=1))

    code_id = new_id("exc")
    await session.execute(
        text(
            "INSERT INTO exemption_codes (id, org_id, code, label, status) VALUES "
            "(:id, :org_id, 'TEST-1', 'Test exemption', 'active')"
        ),
        {"id": code_id, "org_id": org_id},
    )
    return code_id


@pytest.mark.asyncio
async def test_concurrent_reviewers_second_stale_edit_is_rejected(db_session: AsyncSession) -> None:
    org_id, user_a, user_b, doc_id = "org_conc_1", "usr_conc_a", "usr_conc_b", new_id("doc")
    async with db_session.begin():
        code_id = await _seed_org_user_doc(db_session, org_id, user_a, doc_id)
        await db_session.execute(
            text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active')"),
            {"id": user_b, "email": f"{user_b}@example.com"},
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        candidate = await create_manual_candidate(
            db_session, org_id, doc_id, user_a,
            page_no=1, bbox={"x": 0, "y": 0, "w": 10, "h": 10},
            exemption_code_id=code_id, text="secret", note=None,
        )

    # Both reviewers load the manifest before either one edits — both see version 2
    # (create_manual_candidate already bumped it once from the initial seed of 1).
    async with db_session.begin():
        await set_org(db_session, org_id)
        manifest_seen_by_both = await get_manifest_by_doc(db_session, doc_id)
        version_both_saw = manifest_seen_by_both.version

    # Reviewer A patches first, using the version they saw — succeeds, manifest bumps again.
    async with db_session.begin():
        await set_org(db_session, org_id)
        await patch_candidate(
            db_session, org_id, candidate.id, user_a,
            state=None, exemption_code_id=None, bbox=None,
            ai_justification="Reviewer A's note", note="A's edit",
            if_match_version=version_both_saw,
        )

    # Reviewer B still has the OLD version — their edit must be rejected, not silently applied.
    async with db_session.begin():
        await set_org(db_session, org_id)
        with pytest.raises(ApiError) as exc_info:
            await patch_candidate(
                db_session, org_id, candidate.id, user_b,
                state=None, exemption_code_id=None, bbox=None,
                ai_justification="Reviewer B's clobbering note", note="B's stale edit",
                if_match_version=version_both_saw,
            )
        assert exc_info.value.status_code == 409

    # Reviewer A's edit must have survived, untouched by B's rejected attempt.
    async with db_session.begin():
        await set_org(db_session, org_id)
        result = await db_session.execute(
            text("SELECT ai_justification FROM redaction_candidates WHERE id = :id"), {"id": candidate.id}
        )
        assert result.scalar_one() == "Reviewer A's note"

    # Reviewer B retries after re-fetching the current version — now it succeeds.
    async with db_session.begin():
        await set_org(db_session, org_id)
        fresh_manifest = await get_manifest_by_doc(db_session, doc_id)
        updated = await patch_candidate(
            db_session, org_id, candidate.id, user_b,
            state=None, exemption_code_id=None, bbox=None,
            ai_justification="Reviewer B's retried note", note="B's retry",
            if_match_version=fresh_manifest.version,
        )
        assert updated.ai_justification == "Reviewer B's retried note"
