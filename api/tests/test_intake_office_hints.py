"""DOCX/DOC/XLSX/PPTX are deliberately not converted server-side (no LibreOffice in this
environment, and a pure-Python approximation would silently degrade formatting) — users
export to PDF themselves and upload that, same path as any other PDF. This verifies the
rejection is a clear, actionable instruction, not a dead-end "unsupported type" message,
and that a real DOCX's OOXML structure is correctly distinguished from a generic ZIP
(both are ZIP containers under the hood) so it doesn't get routed into ZIP-batch expansion."""

import io
import zipfile

import pytest

from app.pipeline.intake import IntakeError, is_zip_mime, sniff_mime, validate_and_scan


def _minimal_docx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        zf.writestr("word/document.xml", "<document/>")
        zf.writestr("_rels/.rels", "<Relationships/>")
    return buffer.getvalue()


def test_docx_is_not_sniffed_as_a_generic_zip() -> None:
    """A .docx IS a ZIP container under the hood — must not collide with ZIP-batch upload."""
    mime_type = sniff_mime(_minimal_docx_bytes())
    assert mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert not is_zip_mime(mime_type)


def test_validate_and_scan_gives_actionable_hint_for_docx() -> None:
    with pytest.raises(IntakeError) as exc_info:
        validate_and_scan(_minimal_docx_bytes())
    detail = exc_info.value.detail or ""
    assert "Save As" in detail or "Export" in detail
    assert "PDF" in detail


def test_validate_and_scan_generic_message_for_unrelated_unsupported_type() -> None:
    with pytest.raises(IntakeError) as exc_info:
        validate_and_scan(b"just some plain text, not a PDF or office doc")
    detail = exc_info.value.detail or ""
    assert "Unsupported file type" in detail
