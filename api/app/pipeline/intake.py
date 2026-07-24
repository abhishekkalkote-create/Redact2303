"""specs/05-redaction-pipeline.md Stage 1: Intake. Phase 1 scope is single born-digital
PDF only (ZIP/EML/DOCX intake land in Phase 3 per specs/10-build-plan.md)."""

import hashlib

import magic

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.pipeline.malware_scan import get_scanner

ACCEPTED_MIME_TYPES = {"application/pdf"}


class IntakeError(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__(422, "Unprocessable Upload", detail)


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
