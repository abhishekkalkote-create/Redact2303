from pydantic import BaseModel


class LegalHoldRequest(BaseModel):
    """specs/08-security-compliance.md § Data lifecycle: "Legal-hold flag per
    document/request suspends deletion." `note` is optional context (e.g. a case/matter
    reference) captured in the audit trail, not a persisted column."""

    note: str | None = None
