from pydantic import BaseModel, Field

from app.models.organization import DEFAULT_SETTINGS


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    jurisdiction_state: str = Field(min_length=2, max_length=3)
    org_type: str
    use_case: str | None = None
    est_monthly_pages: int | None = None


class OrgSettingsUpdate(BaseModel):
    dual_approval_required: bool | None = None
    default_rule_pack_ids: list[str] | None = None
    retention_days_uploads: int | None = None
    retention_days_exports: int | None = None
    export_defaults: dict | None = None


class OrgOut(BaseModel):
    id: str
    name: str
    slug: str
    jurisdiction_state: str
    org_type: str
    plan: str
    plan_status: str
    settings: dict = DEFAULT_SETTINGS

    model_config = {"from_attributes": True}
