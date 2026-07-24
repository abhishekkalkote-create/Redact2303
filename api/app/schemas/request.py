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

    model_config = {"from_attributes": True}


class RequestPatch(BaseModel):
    title: str | None = None
    status: str | None = None
    due_date: datetime | None = None
    assignee_id: str | None = None
