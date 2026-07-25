from datetime import datetime

from pydantic import BaseModel

from app.schemas.request import RequestOut


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
    request_id: str | None = None
    assignee_id: str | None = None
    due_date: datetime | None = None
    # specs/04-api-spec.md: "GET /documents/{id} detail incl. status, pages,
    # rule_set_version_ids, usage" — which rule_set_versions ran, locked at processing.
    rule_set_version_ids: list[str] | None = None

    model_config = {"from_attributes": True}


class ProcessDocumentRequest(BaseModel):
    """specs/04-api-spec.md POST /documents/{id}/process {rule_pack_ids[]?, priority?}.
    `rule_pack_ids` overrides the org's configured default packs for this run only.
    `priority` is accepted for contract-compatibility with the real SQS-backed workers
    (specs/02-architecture.md) — Phase 1's synchronous-in-request pipeline (app/pipeline/
    run.py's module docstring) has no queue to prioritize against yet, so it's a no-op."""

    rule_pack_ids: list[str] | None = None
    priority: str | None = None


class DocumentAssignPatch(BaseModel):
    assignee_id: str | None = None
    due_date: datetime | None = None
    request_id: str | None = None


class BatchRejection(BaseModel):
    filename: str
    reason: str


class BatchUploadResult(BaseModel):
    """specs/04-api-spec.md: upload finalize "creates document(s)" — always plural, since
    a ZIP batch (specs/05-redaction-pipeline.md Stage 1) may create many. A single-file
    upload is just the degenerate case: one document, zero rejections."""

    documents: list[DocumentOut]
    rejected: list[BatchRejection]
    # Only set when the upload was an .eml/.msg — email intake creates a new Request to
    # group the body-rendered PDF + attachment child documents under.
    request: RequestOut | None = None


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
    escalated_at: datetime | None = None
    escalated_note: str | None = None

    model_config = {"from_attributes": True}


class CandidateEscalateRequest(BaseModel):
    note: str | None = None


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
    # specs/07-ui-spec.md screen 6 taxonomy view: "tree grouped federal/state/org" —
    # `level`/`state` come from the cloned-from ExemptionLibrary row (null for an
    # org-only custom code with no `library_id`, which is itself the "org" group).
    library_id: str | None = None
    level: str | None = None
    state: str | None = None

    model_config = {"from_attributes": True}


class ReviewApprovalRequest(BaseModel):
    note: str | None = None
