"""specs/04-api-spec.md: POST /documents/{id}/process "(re)run detection; re-run creates
new candidates, keeps decisions on unchanged spans." Real Postgres, real PDF extraction,
real rule engine — LLM is faked with an empty canned-response list (FakeLLMProvider's
default "no findings") so detection is fully controlled by an org-owned custom rule pack,
same determinism approach as tests/test_test_bench.py."""

import fitz
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.ids import new_id
from app.llm.provider import FakeLLMProvider
from app.models.document import Document
from app.models.manifest import Manifest
from app.models.organization import Organization
from app.models.redaction_candidate import RedactionCandidate
from app.pipeline.run import process_document, reprocess_document
from app.schemas.rule import RuleCreate, RulePackCreate
from app.services.exemption_service import clone_library_for_org
from app.services.rule_service import (
    add_rule,
    create_rule_pack,
    list_versions_for_pack,
    publish_version,
)
from tests.conftest import set_org


def _sample_pdf(text_content: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text_content)
    data = doc.tobytes()
    doc.close()
    return data


async def _seed_org_and_user(session: AsyncSession, org_id: str, user_id: str) -> None:
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
        text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )


async def _make_pack_with_ssn_rule(session: AsyncSession, org_id: str, user_id: str) -> tuple[str, str]:
    """Returns (pack_id, published_version_id) for a fresh org-owned pack with one active
    SSN entity rule, so a test's detection surface is fully controlled rather than
    depending on the exact content of the seeded starter packs."""
    pack = await create_rule_pack(session, org_id, user_id, RulePackCreate(name="Custom", category="custom"))
    versions = await list_versions_for_pack(session, pack.id)
    draft_id = versions[0].id
    await add_rule(
        session, org_id, user_id, draft_id,
        RuleCreate(rule_key="TEST-SSN", name="SSN", trigger_type="entity", config={"entity_type": "US_SSN"}),
    )
    await publish_version(session, org_id, user_id, draft_id, "v1")
    return pack.id, draft_id


def _set_fake_provider(monkeypatch) -> None:
    monkeypatch.setattr("app.pipeline.run.get_provider", lambda: FakeLLMProvider(canned_responses=[]))


async def _candidates_for_doc(session: AsyncSession, doc_id: str) -> list[RedactionCandidate]:
    result = await session.execute(select(RedactionCandidate).where(RedactionCandidate.doc_id == doc_id))
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_reprocess_preserves_approved_decision_and_id_on_matched_span(db_session: AsyncSession, monkeypatch) -> None:
    org_id, user_id, doc_id = "org_reproc_1", "usr_reproc_1", new_id("doc")
    _set_fake_provider(monkeypatch)

    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)
        exemption_codes = await clone_library_for_org(db_session, org_id, "WA")
        pack_id, _version_id = await _make_pack_with_ssn_rule(db_session, org_id, user_id)
        organization = await db_session.get(Organization, org_id)
        organization.settings = {**organization.settings, "default_rule_pack_ids": [pack_id]}
        original_key = f"originals/{doc_id}"
        from app.storage import get_store

        get_store().put(org_id, original_key, _sample_pdf("SSN 234-56-7890 on file."))
        db_session.add(
            Document(
                id=doc_id, org_id=org_id, filename="sample.pdf", mime_type="application/pdf",
                source="upload", status="uploaded", uploaded_by=user_id, s3_key_original=original_key,
                content_sha256="deadbeef",
            )
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        await process_document(db_session, org_id, doc_id, actor_id=user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        candidates = await _candidates_for_doc(db_session, doc_id)
        assert len(candidates) == 1
        ssn_candidate_id = candidates[0].id
        candidates[0].state = "approved"
        candidates[0].exemption_code_id = exemption_codes[0].id

    async with db_session.begin():
        await set_org(db_session, org_id)
        manifest_before = (await db_session.execute(select(Manifest).where(Manifest.doc_id == doc_id))).scalars().one()
        version_before = manifest_before.version

    async with db_session.begin():
        await set_org(db_session, org_id)
        await reprocess_document(db_session, org_id, doc_id, actor_id=user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        candidates = await _candidates_for_doc(db_session, doc_id)
        assert len(candidates) == 1
        assert candidates[0].id == ssn_candidate_id, "matched span must preserve the original candidate id"
        assert candidates[0].state == "approved", "decision on an unchanged span must survive a re-run"
        assert candidates[0].exemption_code_id == exemption_codes[0].id

        document = await db_session.get(Document, doc_id)
        assert document.status == "ready_for_review"

        manifest_after = (await db_session.execute(select(Manifest).where(Manifest.doc_id == doc_id))).scalars().one()
        assert manifest_after.version == version_before + 1


@pytest.mark.asyncio
async def test_reprocess_keeps_decided_candidate_even_when_no_longer_redetected(db_session: AsyncSession, monkeypatch) -> None:
    org_id, user_id, doc_id = "org_reproc_2", "usr_reproc_2", new_id("doc")
    _set_fake_provider(monkeypatch)

    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)
        await clone_library_for_org(db_session, org_id, "WA")
        pack_id, _version_id = await _make_pack_with_ssn_rule(db_session, org_id, user_id)
        organization = await db_session.get(Organization, org_id)
        organization.settings = {**organization.settings, "default_rule_pack_ids": [pack_id]}
        original_key = f"originals/{doc_id}"
        from app.storage import get_store

        get_store().put(org_id, original_key, _sample_pdf("SSN 234-56-7890 on file."))
        db_session.add(
            Document(
                id=doc_id, org_id=org_id, filename="sample.pdf", mime_type="application/pdf",
                source="upload", status="uploaded", uploaded_by=user_id, s3_key_original=original_key,
                content_sha256="deadbeef",
            )
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        await process_document(db_session, org_id, doc_id, actor_id=user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        candidates = await _candidates_for_doc(db_session, doc_id)
        rejected_candidate_id = candidates[0].id
        candidates[0].state = "rejected"

    # Reprocess with an empty rule pack selection — the SSN rule is no longer active, so
    # nothing detects that span again. It was already decided (rejected), so it must survive.
    async with db_session.begin():
        await set_org(db_session, org_id)
        await reprocess_document(db_session, org_id, doc_id, actor_id=user_id, rule_pack_ids=[])

    async with db_session.begin():
        await set_org(db_session, org_id)
        candidates = await _candidates_for_doc(db_session, doc_id)
        assert len(candidates) == 1
        assert candidates[0].id == rejected_candidate_id
        assert candidates[0].state == "rejected"


@pytest.mark.asyncio
async def test_reprocess_drops_suggested_candidate_when_no_longer_redetected(db_session: AsyncSession, monkeypatch) -> None:
    org_id, user_id, doc_id = "org_reproc_3", "usr_reproc_3", new_id("doc")
    _set_fake_provider(monkeypatch)

    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)
        await clone_library_for_org(db_session, org_id, "WA")
        pack_id, _version_id = await _make_pack_with_ssn_rule(db_session, org_id, user_id)
        organization = await db_session.get(Organization, org_id)
        organization.settings = {**organization.settings, "default_rule_pack_ids": [pack_id]}
        original_key = f"originals/{doc_id}"
        from app.storage import get_store

        get_store().put(org_id, original_key, _sample_pdf("SSN 234-56-7890 on file."))
        db_session.add(
            Document(
                id=doc_id, org_id=org_id, filename="sample.pdf", mime_type="application/pdf",
                source="upload", status="uploaded", uploaded_by=user_id, s3_key_original=original_key,
                content_sha256="deadbeef",
            )
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        await process_document(db_session, org_id, doc_id, actor_id=user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        candidates = await _candidates_for_doc(db_session, doc_id)
        assert len(candidates) == 1
        assert candidates[0].state == "suggested"

    # Disable the SSN rule for this run — the never-decided candidate must be dropped,
    # not left behind as a stale suggestion for a rule that no longer applies.
    async with db_session.begin():
        await set_org(db_session, org_id)
        await reprocess_document(db_session, org_id, doc_id, actor_id=user_id, rule_pack_ids=[])

    async with db_session.begin():
        await set_org(db_session, org_id)
        candidates = await _candidates_for_doc(db_session, doc_id)
        assert candidates == []


@pytest.mark.asyncio
async def test_reprocess_creates_new_suggested_candidate_for_newly_active_rule(db_session: AsyncSession, monkeypatch) -> None:
    org_id, user_id, doc_id = "org_reproc_4", "usr_reproc_4", new_id("doc")
    _set_fake_provider(monkeypatch)

    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)
        await clone_library_for_org(db_session, org_id, "WA")
        pack_id, v1_id = await _make_pack_with_ssn_rule(db_session, org_id, user_id)
        organization = await db_session.get(Organization, org_id)
        organization.settings = {**organization.settings, "default_rule_pack_ids": [pack_id]}
        original_key = f"originals/{doc_id}"
        from app.storage import get_store

        get_store().put(org_id, original_key, _sample_pdf("SSN 234-56-7890 and email jane@example.com on file."))
        db_session.add(
            Document(
                id=doc_id, org_id=org_id, filename="sample.pdf", mime_type="application/pdf",
                source="upload", status="uploaded", uploaded_by=user_id, s3_key_original=original_key,
                content_sha256="deadbeef",
            )
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        await process_document(db_session, org_id, doc_id, actor_id=user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        candidates = await _candidates_for_doc(db_session, doc_id)
        assert len(candidates) == 1  # only SSN so far
        ssn_candidate_id = candidates[0].id

        # Adding a rule to an already-published version forks a new draft (copy-on-write)
        # — add the EMAIL rule there and publish it, so the pack's *active* published
        # version now detects both spans.
        new_rule = await add_rule(
            db_session, org_id, user_id, v1_id,
            RuleCreate(rule_key="TEST-EMAIL", name="Email", trigger_type="entity", config={"entity_type": "EMAIL_ADDRESS"}),
        )
        draft_v2_id = new_rule.rule_set_version_id

    async with db_session.begin():
        await set_org(db_session, org_id)
        await publish_version(db_session, org_id, user_id, draft_v2_id, "v2")

    async with db_session.begin():
        await set_org(db_session, org_id)
        await reprocess_document(db_session, org_id, doc_id, actor_id=user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        candidates = await _candidates_for_doc(db_session, doc_id)
        assert len(candidates) == 2
        by_id = {c.id: c for c in candidates}
        assert by_id[ssn_candidate_id].state == "suggested"  # preserved, same id
        new_candidate = next(c for c in candidates if c.id != ssn_candidate_id)
        assert new_candidate.state == "suggested"


@pytest.mark.asyncio
async def test_reprocess_rejects_disallowed_document_status(db_session: AsyncSession, monkeypatch) -> None:
    org_id, user_id, doc_id = "org_reproc_5", "usr_reproc_5", new_id("doc")
    _set_fake_provider(monkeypatch)

    async with db_session.begin():
        await _seed_org_and_user(db_session, org_id, user_id)
        await clone_library_for_org(db_session, org_id, "WA")
        pack_id, _version_id = await _make_pack_with_ssn_rule(db_session, org_id, user_id)
        organization = await db_session.get(Organization, org_id)
        organization.settings = {**organization.settings, "default_rule_pack_ids": [pack_id]}
        original_key = f"originals/{doc_id}"
        from app.storage import get_store

        get_store().put(org_id, original_key, _sample_pdf("SSN 234-56-7890 on file."))
        db_session.add(
            Document(
                id=doc_id, org_id=org_id, filename="sample.pdf", mime_type="application/pdf",
                source="upload", status="uploaded", uploaded_by=user_id, s3_key_original=original_key,
                content_sha256="deadbeef",
            )
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        await process_document(db_session, org_id, doc_id, actor_id=user_id)

    async with db_session.begin():
        await set_org(db_session, org_id)
        document = await db_session.get(Document, doc_id)
        document.status = "exported"

    with pytest.raises(ApiError):
        async with db_session.begin():
            await set_org(db_session, org_id)
            await reprocess_document(db_session, org_id, doc_id, actor_id=user_id)
