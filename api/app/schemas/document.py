from datetime import datetime

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: str
    filename: str
    mime_type: str
    source: str
    status: str
    page_count: int | None = None
    ocr_used: bool
    uploaded_by: str
    error: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BBox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class CandidateOut(BaseModel):
    id: str
    page_no: int
    bbox: BBox
    display_text: str
    origin: str
    source_rule_key: str | None = None
    exemption_code_id: str | None = None
    exemption_code: str | None = None
    ai_justification: str | None = None
    confidence: str
    state: str

    model_config = {"from_attributes": True}


class ManifestOut(BaseModel):
    doc_id: str
    version: int
    schema_version: int
    completeness: dict
    candidates: list[CandidateOut]


class CandidateCreate(BaseModel):
    page_no: int
    bbox: BBox
    exemption_code_id: str
    note: str | None = None


class CandidatePatch(BaseModel):
    state: str | None = None
    exemption_code_id: str | None = None
    bbox: BBox | None = None
    ai_justification: str | None = None
    note: str | None = None


class SearchRedactRequest(BaseModel):
    query: str
    is_pattern: bool = False
    scope: str = "document"  # "page" | "document" ("request" scope is Phase 3)
    page_no: int | None = None
    exemption_code_id: str


class SearchRedactResponse(BaseModel):
    created: list[CandidateOut]
