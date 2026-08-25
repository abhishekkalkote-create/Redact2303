"""specs/05-redaction-pipeline.md § Golden-file test suite: "Detection changes must
keep recall >= 95% / precision >= 80% on the golden set; export tests assert integrity
verifier passes and text-over-boxes is empty." See fixtures.py's module docstring for
this suite's scope (born-digital, deterministic-only fixtures; OCR- and NER-dependent
categories are out of scope, not silently skipped).
"""

import fitz
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.models.document import Document
from app.pipeline.export import verify_integrity
from app.pipeline.run import process_document
from app.services.exemption_service import clone_library_for_org
from app.services.export_service import create_export
from app.services.review_service import complete_review, patch_candidate
from app.storage import get_store
from tests.conftest import set_org
from tests.pipeline.golden.fixtures import FIXTURES, GoldenFixture

_ORG_ID = "org_golden_suite"
_USER_ID = "usr_golden_suite"


def _generate_pdf(lines: list[str]) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 18
    return doc.tobytes()


async def _seed_org_once(session: AsyncSession) -> None:
    await set_org(session, _ORG_ID)
    existing = await session.execute(text("SELECT 1 FROM organizations WHERE id = :id"), {"id": _ORG_ID})
    if existing.first() is not None:
        return
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'police', 'pilot', 'trialing', '{}')"
        ),
        {"id": _ORG_ID},
    )
    await session.execute(
        text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active') ON CONFLICT (id) DO NOTHING"),
        {"id": _USER_ID, "email": f"{_USER_ID}@example.com"},
    )
    await clone_library_for_org(session, _ORG_ID, "WA")


async def _seed_document(session: AsyncSession, fixture: GoldenFixture, doc_id: str) -> None:
    original_key = f"originals/{doc_id}"
    get_store().put(_ORG_ID, original_key, _generate_pdf(fixture.lines))
    session.add(
        Document(
            id=doc_id, org_id=_ORG_ID, filename=f"{fixture.id}.pdf", mime_type="application/pdf",
            source="sample", status="uploaded", uploaded_by=_USER_ID, s3_key_original=original_key,
            content_sha256="deadbeef",
        )
    )


async def _detected_findings(session: AsyncSession, doc_id: str) -> set[tuple[str, str]]:
    result = await session.execute(
        text(
            "SELECT rc.display_text_encrypted, ec.code FROM redaction_candidates rc "
            "LEFT JOIN exemption_codes ec ON ec.id = rc.exemption_code_id WHERE rc.doc_id = :doc_id"
        ),
        {"doc_id": doc_id},
    )
    rows = result.all()
    cipher = get_cipher()
    return {(cipher.decrypt(_ORG_ID, row.display_text_encrypted), row.code) for row in rows if row.code}


@pytest.mark.asyncio
async def test_golden_set_recall_and_precision(db_session: AsyncSession) -> None:
    total_tp = total_fp = total_fn = 0
    per_fixture_report = []

    for fixture in FIXTURES:
        doc_id = new_id("doc")
        async with db_session.begin():
            await _seed_org_once(db_session)
            await _seed_document(db_session, fixture, doc_id)

        async with db_session.begin():
            await set_org(db_session, _ORG_ID)
            await process_document(db_session, _ORG_ID, doc_id, actor_id=_USER_ID, bill_usage=False)

        async with db_session.begin():
            await set_org(db_session, _ORG_ID)
            found = await _detected_findings(db_session, doc_id)

        expected = {(f.text, f.exemption_code) for f in fixture.expected}
        tp = found & expected
        fp = found - expected
        fn = expected - found
        total_tp += len(tp)
        total_fp += len(fp)
        total_fn += len(fn)
        if fp or fn:
            per_fixture_report.append(f"{fixture.id}: missed={fn or None} unexpected={fp or None}")

    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 1.0
    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 1.0
    report = "; ".join(per_fixture_report)

    assert recall >= 0.95, f"recall {recall:.2%} below 95% target ({total_tp} tp, {total_fn} fn). {report}"
    assert precision >= 0.80, f"precision {precision:.2%} below 80% target ({total_tp} tp, {total_fp} fp). {report}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fixture_id",
    ["police_report_ci_case_ssn_phone", "hr_file_new_hire_ssn_bank_license", "legal_memo_privilege_deliberative_ssn"],
)
async def test_golden_fixture_export_passes_integrity_verification(db_session: AsyncSession, fixture_id: str) -> None:
    """Second half of specs/05's golden-suite requirement: "export tests assert
    integrity verifier passes and text-over-boxes is empty." Runs one representative
    fixture per category all the way through detection -> approve-everything ->
    complete_review -> real create_export, then independently re-verifies the returned
    clean PDF has zero extractable text over every redacted box - not just trusting that
    create_export didn't raise."""
    fixture = next(f for f in FIXTURES if f.id == fixture_id)
    doc_id = new_id("doc")

    async with db_session.begin():
        await _seed_org_once(db_session)
        await _seed_document(db_session, fixture, doc_id)

    async with db_session.begin():
        await set_org(db_session, _ORG_ID)
        await process_document(db_session, _ORG_ID, doc_id, actor_id=_USER_ID, bill_usage=False)

    async with db_session.begin():
        await set_org(db_session, _ORG_ID)
        result = await db_session.execute(
            text("SELECT id, exemption_code_id FROM redaction_candidates WHERE doc_id = :doc_id"), {"doc_id": doc_id}
        )
        candidate_ids = [(row.id, row.exemption_code_id) for row in result.all()]
        assert candidate_ids, f"{fixture_id} produced no candidates to approve/export"
        for candidate_id, exemption_code_id in candidate_ids:
            await patch_candidate(
                db_session, _ORG_ID, candidate_id, _USER_ID,
                state="approved", exemption_code_id=exemption_code_id, bbox=None,
                ai_justification=None, note=None, if_match_version=None,
            )
        await complete_review(db_session, _ORG_ID, doc_id, _USER_ID)

    async with db_session.begin():
        await set_org(db_session, _ORG_ID)
        artifacts = await create_export(db_session, _ORG_ID, doc_id, _USER_ID, types=("clean_pdf",))

    clean_pdf_artifact = next(a for a in artifacts if a.type == "clean_pdf")
    clean_bytes = get_store().get(_ORG_ID, clean_pdf_artifact.s3_key)

    async with db_session.begin():
        await set_org(db_session, _ORG_ID)
        result = await db_session.execute(
            text("SELECT page_no, bbox FROM redaction_candidates WHERE doc_id = :doc_id AND state = 'approved'"),
            {"doc_id": doc_id},
        )
        approved_boxes = [(row.page_no, row.bbox) for row in result.all()]
        redacted_texts = [f.text for f in fixture.expected]

    integrity = verify_integrity(clean_bytes, approved_boxes, redacted_texts)
    assert integrity.passed, f"{fixture_id} export failed integrity verification: {integrity.checks}"

    # Independently confirm no redacted text is recoverable from the clean PDF at all,
    # not just within its own approved bbox (verify_integrity already checks that).
    reextracted = "".join(page.get_text() for page in fitz.open(stream=clean_bytes, filetype="pdf"))
    for finding in fixture.expected:
        assert finding.text not in reextracted, f"{fixture_id}: {finding.text!r} still recoverable in exported PDF"
