"""specs/05-redaction-pipeline.md Stage 1: "ZIP: expand to child documents (flatten one
level; nested zips rejected)." Pure unit tests against app.pipeline.intake.expand_zip —
no DB needed, matches tests/test_foundations.py's style for non-DB pipeline pieces."""

import io
import zipfile

import fitz
import pytest

from app.core.config import Settings
from app.pipeline.intake import IntakeError, expand_zip, is_zip_mime, sniff_mime


def _pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text)
    data = doc.tobytes()
    doc.close()
    return data


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buffer.getvalue()


def test_sniff_mime_and_is_zip_mime() -> None:
    zip_data = _zip_bytes({"a.pdf": _pdf_bytes("A")})
    assert is_zip_mime(sniff_mime(zip_data))
    assert not is_zip_mime(sniff_mime(_pdf_bytes("A")))


def test_expand_zip_returns_all_entries() -> None:
    zip_data = _zip_bytes({"a.pdf": _pdf_bytes("A"), "b.pdf": _pdf_bytes("B")})
    entries, rejected = expand_zip(zip_data)
    assert {name for name, _ in entries} == {"a.pdf", "b.pdf"}
    assert rejected == []


def test_expand_zip_flattens_directory_structure() -> None:
    zip_data = _zip_bytes({"folder/sub/a.pdf": _pdf_bytes("A")})
    entries, rejected = expand_zip(zip_data)
    assert [name for name, _ in entries] == ["a.pdf"]
    assert rejected == []


def test_expand_zip_skips_directory_entries() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(zipfile.ZipInfo("folder/"), "")
        zf.writestr("folder/a.pdf", _pdf_bytes("A"))
    entries, rejected = expand_zip(buffer.getvalue())
    assert [name for name, _ in entries] == ["a.pdf"]
    assert rejected == []


def test_expand_zip_rejects_nested_zip_by_extension() -> None:
    inner_zip = _zip_bytes({"a.pdf": _pdf_bytes("A")})
    outer_zip = _zip_bytes({"good.pdf": _pdf_bytes("B"), "nested.zip": inner_zip})
    entries, rejected = expand_zip(outer_zip)
    assert [name for name, _ in entries] == ["good.pdf"]
    assert rejected == [("nested.zip", "nested ZIP archives are not expanded")]


def test_expand_zip_rejects_nested_zip_by_sniffed_content_even_without_zip_extension() -> None:
    inner_zip = _zip_bytes({"a.pdf": _pdf_bytes("A")})
    outer_zip = _zip_bytes({"good.pdf": _pdf_bytes("B"), "disguised.bin": inner_zip})
    entries, rejected = expand_zip(outer_zip)
    assert [name for name, _ in entries] == ["good.pdf"]
    assert rejected == [("disguised.bin", "nested ZIP archives are not expanded")]


def test_expand_zip_raises_on_corrupt_zip() -> None:
    with pytest.raises(IntakeError):
        expand_zip(b"not a zip file at all")


def test_expand_zip_raises_on_empty_zip() -> None:
    empty_zip = _zip_bytes({})
    with pytest.raises(IntakeError):
        expand_zip(empty_zip)


def test_expand_zip_raises_when_uncompressed_size_exceeds_limit() -> None:
    zip_data = _zip_bytes({"a.pdf": _pdf_bytes("A"), "b.pdf": _pdf_bytes("B")})
    tiny_limit = Settings(max_zip_upload_size_bytes=10)
    with pytest.raises(IntakeError):
        expand_zip(zip_data, tiny_limit)


def test_expand_zip_raises_when_outer_archive_exceeds_size_limit() -> None:
    zip_data = _zip_bytes({"a.pdf": _pdf_bytes("A")})
    tiny_limit = Settings(max_zip_upload_size_bytes=1)
    with pytest.raises(IntakeError):
        expand_zip(zip_data, tiny_limit)
