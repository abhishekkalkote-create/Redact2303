from datetime import datetime

from pydantic import BaseModel


class RequestCreate(BaseModel):
    title: str
    reference_no: str | None = None
    due_date: datetime | None = None
    assignee_id: str | None = None


class RequestOut(BaseModel):
    id: str
    title: str
    reference_no: str | None = None
    status: str
    due_date: datetime | None = None
    assignee_id: str | None = None
    created_at: datetime
    # specs/08-security-compliance.md § Data lifecycle — blocks the retention sweep for
    # every document under this request (app/services/retention_service.py).
    legal_hold: bool = False

    model_config = {"from_attributes": True}


class RequestPatch(BaseModel):
    title: str | None = None
    status: str | None = None
    due_date: datetime | None = None
    assignee_id: str | None = None
