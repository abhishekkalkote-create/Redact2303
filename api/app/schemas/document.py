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
    recurrence_group_id: str | None = None

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


class BulkUpdateRequest(BaseModel):
    action: str  # "approve" | "reject"
    candidate_ids: list[str] | None = None
    recurrence_group_id: str | None = None
    confidence: str | None = None
    exemption_code_id: str | None = None


class BulkUpdateResponse(BaseModel):
    updated: list[CandidateOut]


class PageOut(BaseModel):
    page_no: int
    width: float
    height: float
    rotation: int
    has_text_layer: bool

    model_config = {"from_attributes": True}


class ExemptionCodeOut(BaseModel):
    id: str
    code: str
    label: str
    statute_citation: str | None = None
    description: str | None = None
    status: str

    model_config = {"from_attributes": True}
