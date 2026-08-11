from datetime import datetime

from pydantic import BaseModel


class PerUserUsageOut(BaseModel):
    user_id: str
    user_name: str
    pages_processed: int


class UsageCurrentOut(BaseModel):
    period: str
    plan: str
    cap_kind: str
    totals_by_metric: dict[str, int]
    pages_included: int | None
    pages_used: int
    seats_included: int
    seats_active: int
    overage_pages: int
    overage_cost_cents: int
    per_user_breakdown: list[PerUserUsageOut]


class UsageRecordOut(BaseModel):
    id: str
    metric: str
    quantity: int
    doc_id: str | None
    job_id: str | None
    occurred_at: datetime
    billing_period: str

    model_config = {"from_attributes": True}
