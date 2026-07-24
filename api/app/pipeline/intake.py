"""specs/05-redaction-pipeline.md Stage 1: Intake. Phase 1 scope was single born-digital
PDF only; Phase 3 adds ZIP batch expansion (EML/MSG and DOCX intake remain open gaps)."""

import hashlib
import io
import zipfile

import magic

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.pipeline.malware_scan import get_scanner

ACCEPTED_MIME_TYPES = {"application/pdf"}
ZIP_MIME_TYPES = {"application/zip", "application/x-zip-compressed"}


class IntakeError(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__(422, "Unprocessable Upload", detail)


def sniff_mime(data: bytes) -> str:
    return magic.from_buffer(data, mime=True)


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

    mime_type = magic.from_buffer(data, mime=True)
    if mime_type not in ACCEPTED_MIME_TYPES:
        raise IntakeError(f"Unsupported file type: {mime_type} (only PDF in Phase 1)")

    scanner = get_scanner(settings)
    result = scanner.scan(data)
    if result.infected:
        raise IntakeError(f"Malware detected: {result.virus_name}")

    return mime_type


def content_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
