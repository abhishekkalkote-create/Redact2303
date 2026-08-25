"""specs/05-redaction-pipeline.md Stage 1: Intake. Phase 1 scope was single born-digital
PDF only; Phase 3 adds ZIP batch expansion and EML/MSG (app/pipeline/email_intake.py).

DOCX/DOC/XLSX/PPTX are deliberately NOT converted server-side — no reliable converter is
available in this environment (no LibreOffice), and a lesser pure-Python approximation
would silently degrade formatting/tables/images. Word's own "Export to PDF" already
produces a real, high-fidelity PDF; users are directed to do that and upload the result,
which then goes through the exact same path as any other PDF. `OFFICE_MIME_HINTS` below
turns a raw "unsupported type" 422 into that actionable instruction instead of a dead end.
"""

import hashlib
import io
import zipfile

import magic

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.pipeline.malware_scan import get_scanner

ACCEPTED_MIME_TYPES = {"application/pdf"}
ZIP_MIME_TYPES = {"application/zip", "application/x-zip-compressed"}

OFFICE_MIME_HINTS = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "DOCX files aren't accepted directly. In Word, use File > Save As "
        "(or Export) > PDF, then upload the PDF."
    ),
    "application/msword": (
        "DOC files aren't accepted directly. In Word, use File > Save As "
        "(or Export) > PDF, then upload the PDF."
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        "XLSX files aren't accepted directly. In Excel, use File > Save As "
        "(or Export) > PDF, then upload the PDF."
    ),
    "application/vnd.ms-excel": (
        "XLS files aren't accepted directly. In Excel, use File > Save As "
        "(or Export) > PDF, then upload the PDF."
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        "PPTX files aren't accepted directly. In PowerPoint, use File > Save As "
        "(or Export) > PDF, then upload the PDF."
    ),
    "application/vnd.ms-powerpoint": (
        "PPT files aren't accepted directly. In PowerPoint, use File > Save As "
        "(or Export) > PDF, then upload the PDF."
    ),
}


class IntakeError(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__(422, "Unprocessable Upload", detail)


_OOXML_ENTRY_MARKERS = {
    "word/document.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xl/workbook.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt/presentation.xml": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _sniff_ooxml(data: bytes) -> str | None:
    """libmagic's ability to tell an OOXML document (docx/xlsx/pptx - themselves zip
    archives) apart from a plain zip depends on the installed magic database version;
    older/minimal ones (e.g. a fresh CI runner's default libmagic1) fall back to the
    generic `application/zip`. OOXML's container format guarantees one of these entry
    paths, so check directly instead of trusting libmagic alone for this ambiguity."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return None
    for marker, mime_type in _OOXML_ENTRY_MARKERS.items():
        if marker in names:
            return mime_type
    return None


def sniff_mime(data: bytes) -> str:
    mime_type = magic.from_buffer(data, mime=True)
    if mime_type in ZIP_MIME_TYPES:
        return _sniff_ooxml(data) or mime_type
    return mime_type


def is_zip_mime(mime_type: str) -> bool:
    return mime_type in ZIP_MIME_TYPES


def expand_zip(data: bytes, settings: Settings | None = None) -> tuple[list[tuple[str, bytes]], list[tuple[str, str]]]:
    """specs/05-redaction-pipeline.md Stage 1: "ZIP: expand to child documents (flatten
    one level; nested zips rejected)." Scans the outer archive for malware and bounds its
    total uncompressed size (zip-bomb guard) before touching any entry; each entry still
    needs its own validate_and_scan() call by the caller — this only handles the
    ZIP-specific structural concerns.

    Returns (entries, rejected): `entries` are raw (filename, bytes) pairs that made it
    past ZIP-level screening; `rejected` are (filename, reason) pairs that didn't
    (directories are silently skipped, not rejected — they're not files to reject)."""
    settings = settings or get_settings()

    if len(data) == 0:
        raise IntakeError("Empty ZIP file")
    if len(data) > settings.max_zip_upload_size_bytes:
        raise IntakeError(f"ZIP file exceeds the {settings.max_zip_upload_size_bytes} byte limit")

    scanner = get_scanner(settings)
    result = scanner.scan(data)
    if result.infected:
        raise IntakeError(f"Malware detected in ZIP: {result.virus_name}")

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise IntakeError(f"Corrupt ZIP file: {exc}") from exc

    infos = [info for info in archive.infolist() if not info.is_dir()]
    total_uncompressed = sum(info.file_size for info in infos)
    if total_uncompressed > settings.max_zip_upload_size_bytes:
        raise IntakeError(f"ZIP contents exceed the {settings.max_zip_upload_size_bytes} byte limit uncompressed")

    entries: list[tuple[str, bytes]] = []
    rejected: list[tuple[str, str]] = []
    for info in infos:
        # "flatten one level": drop any directory path inside the archive, whatever its
        # nesting — every file becomes a top-level child document, no folder structure.
        filename = info.filename.rsplit("/", 1)[-1]
        if not filename:
            continue
        if filename.lower().endswith(".zip"):
            rejected.append((filename, "nested ZIP archives are not expanded"))
            continue
        member_bytes = archive.read(info)
        if is_zip_mime(sniff_mime(member_bytes)):
            rejected.append((filename, "nested ZIP archives are not expanded"))
            continue
        entries.append((filename, member_bytes))

    if not entries and not rejected:
        raise IntakeError("ZIP file contains no entries")

    return entries, rejected


def validate_and_scan(data: bytes, settings: Settings | None = None) -> str:
    """Returns the sniffed MIME type. Raises IntakeError on any validation/scan failure.
    MIME is sniffed from content (python-magic), never trusted from the client-supplied
    filename/extension (specs/05-redaction-pipeline.md: "MIME sniff, not extension trust")."""
    settings = settings or get_settings()

    if len(data) == 0:
        raise IntakeError("Empty file")
    if len(data) > settings.max_upload_size_bytes:
        raise IntakeError(f"File exceeds the {settings.max_upload_size_bytes} byte limit")

    mime_type = sniff_mime(data)
    if mime_type not in ACCEPTED_MIME_TYPES:
        hint = OFFICE_MIME_HINTS.get(mime_type)
        if hint:
            raise IntakeError(hint)
        raise IntakeError(f"Unsupported file type: {mime_type}. Upload a PDF, a ZIP of PDFs, or an .eml/.msg.")

    scanner = get_scanner(settings)
    result = scanner.scan(data)
    if result.infected:
        raise IntakeError(f"Malware detected: {result.virus_name}")

    return mime_type


def content_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
