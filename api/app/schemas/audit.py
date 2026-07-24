from datetime import datetime

from pydantic import BaseModel, Field


class AuditEventOut(BaseModel):
    id: str
    actor_type: str
    actor_id: str | None = None
    action: str
    object_type: str
    object_id: str
    created_at: datetime
    # The ORM attribute is `metadata_` (SQLAlchemy reserves `Base.metadata`) — read by that
    # name via from_attributes, but serialize as "metadata" in the API response, which is
    # what it's actually called everywhere else (specs/03-data-model.md, other schemas).
    metadata_: dict = Field(serialization_alias="metadata")

    model_config = {"from_attributes": True}
