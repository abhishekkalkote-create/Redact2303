from datetime import datetime

from pydantic import BaseModel


class PlatformOrgProvisionRequest(BaseModel):
    """specs/09-admin-billing.md § Platform admin: "Org lifecycle: provision
    (sales-assisted)." owner_email is optional — set it to send an immediate
    agency_admin invite; omit it to just create the org shell."""

    name: str
    jurisdiction_state: str
    org_type: str
    plan: str = "pilot"
    owner_email: str | None = None


class PlatformOrgOut(BaseModel):
    id: str
    name: str
    slug: str
    jurisdiction_state: str
    org_type: str
    plan: str
    plan_status: str
    created_at: datetime
    settings: dict

    model_config = {"from_attributes": True}


class PlatformOrgProvisionResponse(BaseModel):
    org: PlatformOrgOut
    invite_token: str | None = None


class PlatformOrgUpdate(BaseModel):
    """specs/09-admin-billing.md: "plan/flag/cap overrides, suspend/reactivate."
    plan_status carries suspend/reactivate (set to "suspended"/"active" — see
    app/auth/deps.py's get_org_db suspension gate). page_cap_override is
    platform-admin-only; never exposed on the org-admin-facing OrgSettingsUpdate."""

    plan: str | None = None
    plan_status: str | None = None
    features: dict[str, bool] | None = None
    page_cap_override: int | None = None


class PlatformUsageOrgSummaryOut(BaseModel):
    org_id: str
    org_name: str
    plan: str
    plan_status: str
    pages_processed: int
    documents: int


class PlatformUsageOut(BaseModel):
    """Cross-tenant usage rollup for the current period. Deliberately NOT the full
    dashboard specs/09-admin-billing.md describes (MRR, margin/COGS, SLO compliance,
    error/DLQ rates, LLM spend, golden-set accuracy trend) — none of that is
    instrumented anywhere in this codebase yet; this exposes only what usage_records
    actually has."""

    period: str
    org_count: int
    orgs: list[PlatformUsageOrgSummaryOut]


class OffboardOrgRequest(BaseModel):
    """specs/08-security-compliance.md § Data lifecycle: org offboarding. confirm_slug
    must match the organization's actual slug — a cheap guard against offboarding the
    wrong org by a mistyped id, on top of an action that's already platform-admin-only
    and fully audited."""

    confirm_slug: str
