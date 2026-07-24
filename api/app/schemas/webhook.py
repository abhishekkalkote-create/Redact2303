from datetime import datetime

from pydantic import BaseModel, Field


class WebhookSubscriptionCreate(BaseModel):
    url: str = Field(min_length=1)
    events: list[str]


class WebhookSubscriptionOut(BaseModel):
    id: str
    url: str
    events: list[str]
    status: str
    created_at: datetime
    # Only populated on the create response — same pattern as InviteOut.token (see
    # app/schemas/membership.py): the plaintext secret is never persisted and never
    # returned again after this one response.
    secret: str | None = None

    model_config = {"from_attributes": True}


class WebhookDeliveryOut(BaseModel):
    id: str
    subscription_id: str
    event: str
    status: str
    attempt_count: int
    response_status: int | None = None
    error: str | None = None
    last_attempted_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
