"""specs/09-admin-billing.md § Platform admin: "Org lifecycle: provision (sales-assisted),
plan/flag/cap overrides, suspend/reactivate." specs/04-api-spec.md: GET/POST/PATCH
/platform/orgs, GET /platform/usage — see app/routers/platform.py.

Reads of the org directory (list/get any org) go through app/db/session.py's
system_session() (migration 0011's additive, SELECT-only RLS policy) since a platform
admin has no membership to scope a normal org_session to. Writes to one specific org's
row go through the ordinary org_session(org_id) instead — its standard tenant_isolation
policy already permits that, no exemption needed.

NOT built here (explicitly out of scope, not silently skipped): margin/COGS model,
SLO/error/DLQ dashboards, LLM spend tracking, golden-set accuracy trend — none of that
data is instrumented anywhere in this codebase yet. get_cross_tenant_usage only
aggregates what usage_records actually has: pages/docs/exports by org.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.billing.provider import get_billing_provider
from app.core.errors import ConflictError, NotFoundError
from app.core.ids import new_id
from app.core.slug import slugify
from app.db.session import list_all_org_ids, org_session, system_session
from app.models.organization import DEFAULT_SETTINGS, Organization
from app.models.usage_record import UsageRecord
from app.services.audit_service import write_audit_event
from app.services.exemption_service import clone_library_for_org
from app.services.invite_service import create_invite

MAX_SLUG_ATTEMPTS = 5


async def provision_org(
    platform_admin_user_id: str, *, name: str, jurisdiction_state: str, org_type: str, plan: str,
    owner_email: str | None,
) -> tuple[Organization, str | None]:
    """Sales-assisted provisioning: skips create_org's self-signup "one org per user"
    check entirely (there's no owner account yet) and, if given an owner email, sends
    them an agency_admin invite immediately so they land in a working org on first
    login. Mirrors create_org's slug-collision retry loop."""
    base_slug = slugify(name)
    jurisdiction_state = jurisdiction_state.upper()

    for attempt in range(1, MAX_SLUG_ATTEMPTS + 1):
        slug = base_slug if attempt == 1 else f"{base_slug}-{attempt}"
        org_id = new_id("org")
        customer_id = await get_billing_provider().create_customer(org_id, name, owner_email or "")
        try:
            async with org_session(org_id) as session:
                org = Organization(
                    id=org_id, name=name, slug=slug, jurisdiction_state=jurisdiction_state,
                    org_type=org_type, plan=plan, plan_status="trialing",
                    settings=dict(DEFAULT_SETTINGS), stripe_customer_id=customer_id,
                )
                session.add(org)
                await session.flush()
                await clone_library_for_org(session, org_id, jurisdiction_state)

                invite_token = None
                if owner_email:
                    _, invite_token = await create_invite(session, org_id, platform_admin_user_id, owner_email, "agency_admin")

                await write_audit_event(
                    session, org_id=org_id, actor_type="platform_admin", actor_id=platform_admin_user_id,
                    action="platform.org_provisioned", object_type="organization", object_id=org_id,
                    metadata={"org_type": org_type, "plan": plan, "jurisdiction_state": jurisdiction_state},
                )
                await session.flush()
                await session.refresh(org)
                return org, invite_token
        except IntegrityError as exc:
            if "uq" not in str(exc.orig).lower() and "slug" not in str(exc.orig).lower():
                raise
            continue

    raise ConflictError(f"Could not allocate a unique slug for '{name}'")


async def list_orgs_for_platform() -> list[Organization]:
    async with system_session() as session:
        result = await session.execute(select(Organization).order_by(Organization.created_at.desc()))
        return list(result.scalars().all())


async def get_org_for_platform(org_id: str) -> Organization | None:
    async with system_session() as session:
        return await session.get(Organization, org_id)


async def update_org_for_platform(platform_admin_user_id: str, org_id: str, updates: dict[str, Any]) -> Organization:
    """`updates` may contain: plan, plan_status, features (merged into
    org.settings["features"]), page_cap_override (merged into org.settings — see
    app/services/usage_service.py's effective_pages_included)."""
    async with org_session(org_id) as session:
        org = await session.get(Organization, org_id)
        if org is None:
            raise NotFoundError("Organization not found")

        if "plan" in updates:
            org.plan = updates["plan"]
        if "plan_status" in updates:
            org.plan_status = updates["plan_status"]
        settings_patch: dict[str, Any] = {}
        if "features" in updates:
            settings_patch["features"] = {**org.settings.get("features", {}), **updates["features"]}
        if "page_cap_override" in updates:
            settings_patch["page_cap_override"] = updates["page_cap_override"]
        if settings_patch:
            org.settings = {**org.settings, **settings_patch}

        await write_audit_event(
            session, org_id=org_id, actor_type="platform_admin", actor_id=platform_admin_user_id,
            action="platform.org_updated", object_type="organization", object_id=org_id,
            metadata={"updates": updates},
        )
        await session.flush()
        await session.refresh(org)
        return org


async def get_cross_tenant_usage(now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    period = now.strftime("%Y-%m")
    orgs_summary = []
    for org_id in await list_all_org_ids():
        async with org_session(org_id) as session:
            org = await session.get(Organization, org_id)
            if org is None:
                continue
            totals_result = await session.execute(
                select(UsageRecord.metric, func.sum(UsageRecord.quantity))
                .where(UsageRecord.org_id == org_id, UsageRecord.billing_period == period)
                .group_by(UsageRecord.metric)
            )
            totals_by_metric = {metric: int(total) for metric, total in totals_result.all()}
            orgs_summary.append(
                {
                    "org_id": org.id, "org_name": org.name, "plan": org.plan, "plan_status": org.plan_status,
                    "pages_processed": totals_by_metric.get("pages_processed", 0),
                    "documents": totals_by_metric.get("documents", 0),
                }
            )

    return {
        "period": period,
        "org_count": len(orgs_summary),
        "orgs": sorted(orgs_summary, key=lambda o: o["pages_processed"], reverse=True),
    }
