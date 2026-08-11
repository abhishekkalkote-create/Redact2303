from datetime import UTC, datetime

from pydantic import BaseModel

from app.models.support_grant import SupportGrant


class SupportGrantRequest(BaseModel):
    org_id: str
    reason: str


class SupportGrantOut(BaseModel):
    id: str
    org_id: str
    requested_by: str
    reason: str
    status: str
    requested_at: datetime
    decided_by: str | None
    decided_at: datetime | None
    expires_at: datetime | None
    # specs/08-security-compliance.md: "<= 24h" grant — computed at read time from
    # status + expires_at (see app/models/support_grant.py's GRANT_STATUSES docstring
    # for why nothing stores an "expired" status), not a plain ORM attribute — built via
    # from_support_grant() below rather than model_validate(grant, from_attributes=True).
    is_active: bool

    @classmethod
    def from_support_grant(cls, grant: SupportGrant) -> "SupportGrantOut":
        is_active = grant.status == "approved" and grant.expires_at is not None and grant.expires_at > datetime.now(UTC)
        return cls(
            id=grant.id, org_id=grant.org_id, requested_by=grant.requested_by, reason=grant.reason,
            status=grant.status, requested_at=grant.requested_at, decided_by=grant.decided_by,
            decided_at=grant.decided_at, expires_at=grant.expires_at, is_active=is_active,
        )
