"""specs/01-product-spec.md US-11 / specs/05-redaction-pipeline.md: rejected AI
candidates by rule + reviewer-added manual redactions clustered by text pattern ->
"suggested rule improvements" report for admins. Report only — asserts no rule row is
ever touched by generating it."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.models.document import Document
from app.models.exemption_code import ExemptionCode
from app.models.redaction_candidate import RedactionCandidate
from app.services.rule_service import get_rule_improvements_report
from tests.conftest import set_org


async def _seed_org_user_and_doc(session: AsyncSession, org_id: str, user_id: str, doc_id: str) -> None:
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


def _candidate(org_id: str, doc_id: str, *, origin: str, state: str, source_rule_key: str | None = None,
                text_value: str = "x", exemption_code_id: str | None = None) -> RedactionCandidate:
    cipher = get_cipher()
    return RedactionCandidate(
        id=new_id("cand"), org_id=org_id, doc_id=doc_id, page_no=1, bbox={"x": 0, "y": 0, "w": 1, "h": 1},
        display_text_encrypted=cipher.encrypt(org_id, text_value), origin=origin,
        source_rule_key=source_rule_key, exemption_code_id=exemption_code_id,
        confidence="n/a-manual" if origin == "manual" else "medium", state=state, detector_versions={},
    )


@pytest.mark.asyncio
async def test_report_aggregates_rejections_by_rule_key(db_session: AsyncSession) -> None:
    org_id, user_id, doc_id = "org_ruleimp_1", "usr_ruleimp_1", new_id("doc")
    async with db_session.begin():
        await _seed_org_user_and_doc(db_session, org_id, user_id, doc_id)
        code = ExemptionCode(id=new_id("exc"), org_id=org_id, code="b6", label="Personal privacy", status="active")
        db_session.add(code)
        db_session.add_all([
            _candidate(org_id, doc_id, origin="deterministic", state="rejected", source_rule_key="CORE-SSN"),
            _candidate(org_id, doc_id, origin="deterministic", state="rejected", source_rule_key="CORE-SSN"),
            _candidate(org_id, doc_id, origin="deterministic", state="approved", source_rule_key="CORE-SSN", exemption_code_id=code.id),
            _candidate(org_id, doc_id, origin="llm", state="approved", source_rule_key="CTX-NAME", exemption_code_id=code.id),
        ])

    async with db_session.begin():
        await set_org(db_session, org_id)
        report = await get_rule_improvements_report(db_session, org_id)

    by_key = {r["rule_key"]: r for r in report["rejected_by_rule"]}
    assert by_key["CORE-SSN"]["total_count"] == 3
    assert by_key["CORE-SSN"]["rejected_count"] == 2
    assert by_key["CORE-SSN"]["rejection_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert by_key["CTX-NAME"]["rejected_count"] == 0


@pytest.mark.asyncio
async def test_report_ignores_candidates_without_a_source_rule(db_session: AsyncSession) -> None:
    """search_apply candidates have no source_rule_key — they can't tell an admin
    anything about which *rule* to fix, so they're excluded from the rejected-by-rule
    bucket (they'd still show up as manual-style feedback if they were manual, but
    search_apply isn't)."""
    org_id, user_id, doc_id = "org_ruleimp_2", "usr_ruleimp_2", new_id("doc")
    async with db_session.begin():
        await _seed_org_user_and_doc(db_session, org_id, user_id, doc_id)
        db_session.add_all([
            _candidate(org_id, doc_id, origin="search_apply", state="rejected", source_rule_key=None),
        ])

    async with db_session.begin():
        await set_org(db_session, org_id)
        report = await get_rule_improvements_report(db_session, org_id)

    assert report["rejected_by_rule"] == []


@pytest.mark.asyncio
async def test_report_clusters_manual_redactions_by_normalized_text_pattern(db_session: AsyncSession) -> None:
    org_id, user_id, doc_id = "org_ruleimp_3", "usr_ruleimp_3", new_id("doc")
    async with db_session.begin():
        await _seed_org_user_and_doc(db_session, org_id, user_id, doc_id)
        code = ExemptionCode(
            id=new_id("exc"), org_id=org_id, code="b6", label="Personal privacy", status="active",
        )
        db_session.add(code)
        db_session.add_all([
            _candidate(org_id, doc_id, origin="manual", state="approved", text_value="Case 2024-001", exemption_code_id=code.id),
            _candidate(org_id, doc_id, origin="manual", state="approved", text_value="Case 2024-002", exemption_code_id=code.id),
            _candidate(org_id, doc_id, origin="manual", state="approved", text_value="Case 2024-003", exemption_code_id=code.id),
            # A one-off, differently-shaped manual redaction — shouldn't form its own
            # cluster (below MIN_MANUAL_CLUSTER_SIZE).
            _candidate(org_id, doc_id, origin="manual", state="approved", text_value="Special note here", exemption_code_id=code.id),
        ])

    async with db_session.begin():
        await set_org(db_session, org_id)
        report = await get_rule_improvements_report(db_session, org_id)

    assert len(report["manual_clusters"]) == 1
    cluster = report["manual_clusters"][0]
    assert cluster["count"] == 3
    assert cluster["pattern"] == "case #-#"
    assert cluster["exemption_codes"] == ["b6"]
    assert any("2024" in s for s in cluster["sample_texts"])


@pytest.mark.asyncio
async def test_report_never_mutates_any_rule(db_session: AsyncSession) -> None:
    """specs/01 US-11: "v1: report only; no auto-learning." Belt-and-suspenders check —
    generating the report must not create/edit/delete a row in `rules`."""
    org_id, user_id, doc_id = "org_ruleimp_4", "usr_ruleimp_4", new_id("doc")
    async with db_session.begin():
        await _seed_org_user_and_doc(db_session, org_id, user_id, doc_id)
        db_session.add(_candidate(org_id, doc_id, origin="deterministic", state="rejected", source_rule_key="CORE-SSN"))

    async with db_session.begin():
        await set_org(db_session, org_id)
        before = (await db_session.execute(text("SELECT count(*) FROM rules"))).scalar()
        await get_rule_improvements_report(db_session, org_id)
        after = (await db_session.execute(text("SELECT count(*) FROM rules"))).scalar()

    assert before == after
