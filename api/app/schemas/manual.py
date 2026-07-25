from datetime import datetime

from pydantic import BaseModel


class ManualOut(BaseModel):
    id: str
    filename: str
    uploaded_by: str
    extraction_status: str
    error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DraftRuleOut(BaseModel):
    id: str
    manual_id: str
    rule_key: str | None = None
    name: str
    trigger_type: str
    config: dict
    exemption_code_id: str | None = None
    priority: int
    confidence_policy: str
    exclusions: list
    scope: str
    source_ref: str | None = None
    ai_notes: str | None = None
    status: str

    model_config = {"from_attributes": True}


class DraftRuleAcceptRequest(BaseModel):
    rule_set_version_id: str
    rule_key: str
    # Allow the human to correct the AI's suggestion before landing it as a real rule.
    name: str | None = None
    trigger_type: str | None = None
    config: dict | None = None
    exemption_code_id: str | None = None
    exclusions: list | None = None


class DraftRuleRejectRequest(BaseModel):
    note: str | None = None
