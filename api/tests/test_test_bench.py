"""specs/06-exemption-taxonomy.md § Test bench: "run draft version against selected
sample documents; show would-be candidates + diff vs current published version." Real
Postgres, real PDF text extraction, real rule engine execution — nothing faked here
(no LLM involved; test bench is deterministic-rules-only, same scope as
app/pipeline/detect.py)."""

import fitz
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.models.document import Document
from app.schemas.rule import RuleCreate, RulePackCreate
from app.services.rule_service import (
    add_rule,
    create_rule_pack,
    delete_rule,
    list_versions_for_pack,
    publish_version,
    run_test_bench,
)
from app.storage import get_store
from tests.conftest import set_org


def _sample_pdf(text_content: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text_content)
    data = doc.tobytes()
    doc.close()
    return data


async def _seed_org_user_and_doc(session: AsyncSession, org_id: str, user_id: str, doc_id: str, pdf_bytes: bytes) -> None:
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
    s3_key = f"originals/{doc_id}"
    get_store().put(org_id, s3_key, pdf_bytes)
    session.add(
        Document(
            id=doc_id, org_id=org_id, filename="sample.pdf", mime_type="application/pdf",
            source="upload", status="ready_for_review", uploaded_by=user_id,
            s3_key_original=s3_key, content_sha256="deadbeef",
        )
    )


@pytest.mark.asyncio
async def test_bench_shows_added_matches_when_pack_never_published(db_session: AsyncSession) -> None:
    org_id, user_id, doc_id = "org_bench_1", "usr_bench_1", new_id("doc")
    async with db_session.begin():
        await _seed_org_user_and_doc(db_session, org_id, user_id, doc_id, _sample_pdf("Contact SSN 234-56-7890 today."))

    async with db_session.begin():
        await set_org(db_session, org_id)
        pack = await create_rule_pack(db_session, org_id, user_id, RulePackCreate(name="Custom", category="custom"))
        versions = await list_versions_for_pack(db_session, pack.id)
        draft_version_id = versions[0].id
        await add_rule(
            db_session, org_id, user_id, draft_version_id,
            RuleCreate(rule_key="TEST-SSN", name="SSN", trigger_type="entity", config={"entity_type": "US_SSN"}),
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        result = await run_test_bench(db_session, org_id, user_id, draft_version_id, [doc_id])

    assert result["published_version_id"] is None
    assert len(result["added"]) == 1
    assert result["added"][0]["rule_key"] == "TEST-SSN"
    assert "234-56-7890" in result["added"][0]["text"]
    assert result["removed"] == []
    assert result["unchanged"] == []


@pytest.mark.asyncio
async def test_bench_diffs_draft_against_published_version(db_session: AsyncSession) -> None:
    org_id, user_id, doc_id = "org_bench_2", "usr_bench_2", new_id("doc")
    pdf_bytes = _sample_pdf("SSN 234-56-7890 and email jane@example.com are on file.")
    async with db_session.begin():
        await _seed_org_user_and_doc(db_session, org_id, user_id, doc_id, pdf_bytes)

    async with db_session.begin():
        await set_org(db_session, org_id)
        pack = await create_rule_pack(db_session, org_id, user_id, RulePackCreate(name="Custom", category="custom"))
        versions = await list_versions_for_pack(db_session, pack.id)
        v1_id = versions[0].id
        await add_rule(
            db_session, org_id, user_id, v1_id,
            RuleCreate(rule_key="TEST-SSN", name="SSN", trigger_type="entity", config={"entity_type": "US_SSN"}),
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        await publish_version(db_session, org_id, user_id, v1_id, "v1")

    # Editing the published version forks a new draft (v2) — add an EMAIL rule there,
    # so v2 should show SSN as "unchanged" (present in both) and EMAIL as "added".
    async with db_session.begin():
        await set_org(db_session, org_id)
        new_rule = await add_rule(
            db_session, org_id, user_id, v1_id,
            RuleCreate(rule_key="TEST-EMAIL", name="Email", trigger_type="entity", config={"entity_type": "EMAIL_ADDRESS"}),
        )
        draft_v2_id = new_rule.rule_set_version_id

    async with db_session.begin():
        await set_org(db_session, org_id)
        result = await run_test_bench(db_session, org_id, user_id, draft_v2_id, [doc_id])

    assert result["published_version_id"] == v1_id
    added_keys = {m["rule_key"] for m in result["added"]}
    unchanged_keys = {m["rule_key"] for m in result["unchanged"]}
    assert added_keys == {"TEST-EMAIL"}
    assert unchanged_keys == {"TEST-SSN"}
    assert result["removed"] == []


@pytest.mark.asyncio
async def test_bench_shows_removed_when_draft_drops_a_previously_published_rule(db_session: AsyncSession) -> None:
    org_id, user_id, doc_id = "org_bench_3", "usr_bench_3", new_id("doc")
    pdf_bytes = _sample_pdf("SSN 234-56-7890 and email jane@example.com are on file.")
    async with db_session.begin():
        await _seed_org_user_and_doc(db_session, org_id, user_id, doc_id, pdf_bytes)

    async with db_session.begin():
        await set_org(db_session, org_id)
        pack = await create_rule_pack(db_session, org_id, user_id, RulePackCreate(name="Custom", category="custom"))
        versions = await list_versions_for_pack(db_session, pack.id)
        v1_id = versions[0].id
        ssn_rule = await add_rule(
            db_session, org_id, user_id, v1_id,
            RuleCreate(rule_key="TEST-SSN", name="SSN", trigger_type="entity", config={"entity_type": "US_SSN"}),
        )
        await add_rule(
            db_session, org_id, user_id, v1_id,
            RuleCreate(rule_key="TEST-EMAIL", name="Email", trigger_type="entity", config={"entity_type": "EMAIL_ADDRESS"}),
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        await publish_version(db_session, org_id, user_id, v1_id, "v1")

    async with db_session.begin():
        await set_org(db_session, org_id)
        await delete_rule(db_session, org_id, user_id, ssn_rule.id)  # forks v2, drops SSN rule

    async with db_session.begin():
        await set_org(db_session, org_id)
        versions_after = await list_versions_for_pack(db_session, pack.id)
        draft_v2_id = next(v.id for v in versions_after if v.status == "draft")
        result = await run_test_bench(db_session, org_id, user_id, draft_v2_id, [doc_id])

    removed_keys = {m["rule_key"] for m in result["removed"]}
    unchanged_keys = {m["rule_key"] for m in result["unchanged"]}
    assert removed_keys == {"TEST-SSN"}
    assert unchanged_keys == {"TEST-EMAIL"}
