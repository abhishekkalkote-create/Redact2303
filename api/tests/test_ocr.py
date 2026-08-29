"""app/pipeline/ocr.py + its wiring into app/pipeline/extract.py. Textract is mocked to
fail in every test here (via monkeypatch, not "no AWS creds in CI") so these
deterministically exercise the Tesseract fallback regardless of environment - real
Textract behavior is verified separately (see ga_readiness_punchlist memory), since
pytest shouldn't depend on live AWS credentials/cost to pass in CI.
"""

import fitz
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.crypto.envelope import get_cipher
from app.models.document import Document
from app.pipeline import ocr as ocr_module
from app.pipeline.extract import PREVIEW_DPI, extract_pdf
from app.pipeline.ocr import extract_page_via_ocr
from app.pipeline.run import process_document
from app.services.exemption_service import clone_library_for_org
from app.storage import get_store
from tests.conftest import set_org


def _force_textract_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated Textract failure - forcing the Tesseract fallback path")

    monkeypatch.setattr(ocr_module, "_ocr_via_textract", _raise)


def _render_page_to_png(lines: list[str]) -> tuple[bytes, float, float]:
    """A page with a real, selectable text layer - used only to rasterize into an image
    below, standing in for a real scan. The PDF built from that image has no text
    layer of its own, exactly like a real scanned document."""
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=14)
        y += 24
    pixmap = page.get_pixmap(dpi=PREVIEW_DPI)
    png_bytes = pixmap.tobytes("png")
    width, height = page.rect.width, page.rect.height
    doc.close()
    return png_bytes, width, height


def _generate_scanned_pdf(lines: list[str]) -> bytes:
    """Image-only PDF (one page): rasterize `lines` as text, then embed that image into a
    fresh page with no text layer of its own - i.e. a synthetic scan."""
    png_bytes, width, height = _render_page_to_png(lines)
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.insert_image(page.rect, stream=png_bytes)
    result = doc.tobytes()
    doc.close()
    return result


def test_tesseract_recovers_text_and_plausible_bboxes(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_textract_failure(monkeypatch)
    png_bytes, width, height = _render_page_to_png(["CASE NUMBER 2025-40817", "SSN 452-88-3017"])

    result = extract_page_via_ocr(png_bytes, width, height, dpi=PREVIEW_DPI)

    assert "2025-40817" in result.full_text
    assert "452-88-3017" in result.full_text
    assert 0.0 < result.confidence <= 1.0
    for _start, _end, word_box in result.word_spans:
        assert 0.0 <= word_box.x0 < word_box.x1 <= width
        assert 0.0 <= word_box.y0 < word_box.y1 <= height


def test_extract_pdf_falls_back_to_ocr_for_image_only_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_textract_failure(monkeypatch)
    scanned_pdf = _generate_scanned_pdf(["INCIDENT REPORT", "Case #2025-51203 remains an open investigation."])

    pages = extract_pdf(scanned_pdf)

    assert len(pages) == 1
    page = pages[0]
    assert page.has_text_layer is True
    assert page.ocr_confidence is not None
    assert 0.0 < page.ocr_confidence <= 1.0
    assert "2025-51203" in page.full_text


def test_extract_pdf_leaves_born_digital_pages_untouched_by_ocr() -> None:
    """A page WITH a native text layer must never take the OCR path at all - no Textract
    call, no ocr_confidence set - even though Textract isn't mocked in this test."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "This page has a real text layer.")
    born_digital_pdf = doc.tobytes()
    doc.close()

    pages = extract_pdf(born_digital_pdf)

    assert len(pages) == 1
    assert pages[0].ocr_confidence is None
    assert pages[0].has_text_layer is True


@pytest.mark.asyncio
async def test_process_document_detects_pii_on_a_scanned_document(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves OCR'd text flows all the way through detect -> merge -> a real
    redaction_candidate, the same as a born-digital document - not just that extraction
    recovers text in isolation."""
    _force_textract_failure(monkeypatch)
    org_id, user_id, doc_id = "org_ocr_pipeline", "usr_ocr_pipeline", new_id("doc")
    scanned_pdf = _generate_scanned_pdf(["INCIDENT REPORT", "Complainant SSN on file: 267-90-1145."])

    async with db_session.begin():
        await set_org(db_session, org_id)
        await db_session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
                "plan, plan_status, settings) VALUES "
                "(:id, :id, :id, 'WA', 'police', 'pilot', 'trialing', '{}')"
            ),
            {"id": org_id},
        )
        await db_session.execute(
            text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active')"),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
        await clone_library_for_org(db_session, org_id, "WA")
        original_key = f"originals/{doc_id}"
        get_store().put(org_id, original_key, scanned_pdf)
        db_session.add(
            Document(
                id=doc_id, org_id=org_id, filename="scanned.pdf", mime_type="application/pdf",
                source="sample", status="uploaded", uploaded_by=user_id, s3_key_original=original_key,
                content_sha256="deadbeef",
            )
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        manifest = await process_document(db_session, org_id, doc_id, actor_id=user_id, bill_usage=False)
        assert manifest.doc_id == doc_id

    async with db_session.begin():
        await set_org(db_session, org_id)
        doc_page = (
            await db_session.execute(text("SELECT ocr_confidence, has_text_layer FROM document_pages WHERE doc_id = :id"), {"id": doc_id})
        ).one()
        assert doc_page.has_text_layer is True
        assert doc_page.ocr_confidence is not None

        result = await db_session.execute(
            text(
                "SELECT rc.display_text_encrypted, ec.code FROM redaction_candidates rc "
                "LEFT JOIN exemption_codes ec ON ec.id = rc.exemption_code_id WHERE rc.doc_id = :doc_id"
            ),
            {"doc_id": doc_id},
        )
        rows = result.all()

    cipher = get_cipher()
    found = {(cipher.decrypt(org_id, row.display_text_encrypted), row.code) for row in rows if row.code}
    assert ("267-90-1145", "b(6)") in found
