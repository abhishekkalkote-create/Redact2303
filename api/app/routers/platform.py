"""specs/04-api-spec.md § Platform admin. The spec frames this as "separate subdomain,
separate Cognito app client" — that's an infra/deployment-topology decision (a second
Terraform-provisioned app client, a second frontend deploy target) this slice doesn't
touch. What's built here is the actual authorization boundary: require_platform_admin
(app/auth/deps.py) checked against the platform_admins table, layered on the existing
Cognito/dev-auth flow. Mounted under the same /v1 prefix as everything else and included
in the OpenAPI schema — the web app's /platform/* route group (gated on the same role)
uses the same generated TS client as any other page.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from app.auth.deps import require_platform_admin
from app.core.errors import NotFoundError
from app.models.user import User
from app.schemas.platform import (
    PlatformOrgOut,
    PlatformOrgProvisionRequest,
    PlatformOrgProvisionResponse,
    PlatformOrgUpdate,
    PlatformUsageOut,
)
from app.schemas.support_grant import SupportGrantOut, SupportGrantRequest
from app.services.platform_service import (
    get_cross_tenant_usage,
    get_org_for_platform,
    list_orgs_for_platform,
    provision_org,
    update_org_for_platform,
)
from app.services.support_grant_service import request_grant

router = APIRouter(prefix="/platform", tags=["platform-admin"], dependencies=[Depends(require_platform_admin)])


@router.post("/orgs", response_model=PlatformOrgProvisionResponse, status_code=201)
async def provision_platform_org(
    payload: PlatformOrgProvisionRequest, admin: User = Depends(require_platform_admin)
) -> PlatformOrgProvisionResponse:
    org, invite_token = await provision_org(
        admin.id, name=payload.name, jurisdiction_state=payload.jurisdiction_state,
        org_type=payload.org_type, plan=payload.plan, owner_email=payload.owner_email,
    )
    return PlatformOrgProvisionResponse(org=PlatformOrgOut.model_validate(org), invite_token=invite_token)


@router.get("/orgs", response_model=list[PlatformOrgOut])
async def list_platform_orgs() -> list[PlatformOrgOut]:
    return [PlatformOrgOut.model_validate(org) for org in await list_orgs_for_platform()]


@router.get("/orgs/{org_id}", response_model=PlatformOrgOut)
async def get_platform_org(org_id: str) -> PlatformOrgOut:
    org = await get_org_for_platform(org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    return PlatformOrgOut.model_validate(org)


@router.patch("/orgs/{org_id}", response_model=PlatformOrgOut)
async def update_platform_org(
    org_id: str, payload: PlatformOrgUpdate, admin: User = Depends(require_platform_admin)
) -> PlatformOrgOut:
    updates = payload.model_dump(exclude_none=True)
    org = await update_org_for_platform(admin.id, org_id, updates)
    return PlatformOrgOut.model_validate(org)


@router.get("/usage", response_model=PlatformUsageOut)
async def get_platform_usage() -> PlatformUsageOut:
    return PlatformUsageOut(**await get_cross_tenant_usage(datetime.now(UTC)))


@router.post("/support-grants", response_model=SupportGrantOut, status_code=201)
async def create_support_grant_request(
    payload: SupportGrantRequest, admin: User = Depends(require_platform_admin)
) -> SupportGrantOut:
    grant = await request_grant(admin.id, payload.org_id, payload.reason)
    return SupportGrantOut.from_support_grant(grant)
