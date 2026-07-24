from datetime import datetime

from pydantic import BaseModel, EmailStr


class MemberOut(BaseModel):
    id: str
    user_id: str
    email: str
    name: str
    role: str
    status: str
    last_active_at: datetime | None = None

    model_config = {"from_attributes": True}


class MemberUpdate(BaseModel):
    role: str | None = None
    status: str | None = None


class InviteCreate(BaseModel):
    email: EmailStr
    role: str


class InviteOut(BaseModel):
    id: str
    org_id: str
    email: str
    role: str
    expires_at: datetime
    accepted_at: datetime | None = None
    token: str | None = None
    """Only populated on the create response — there is no email delivery yet (Phase 3),
    so the raw token has to travel back to the caller some way. Never returned by any
    endpoint that re-fetches an existing invite (there isn't one in Phase 0), and never
    stored: `Invite.token_hash` is the only persisted form."""

    model_config = {"from_attributes": True}
