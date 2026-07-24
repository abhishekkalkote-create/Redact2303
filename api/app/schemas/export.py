from datetime import datetime

from pydantic import BaseModel


class ExportOut(BaseModel):
    id: str
    doc_id: str | None
    type: str
    sha256: str
    manifest_version: int
    integrity_check: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class ExportRequest(BaseModel):
    types: list[str] = ["clean_pdf", "exemption_log_csv", "certificate_pdf"]


class CertificateVerifyResponse(BaseModel):
    valid: bool
    facts: dict
