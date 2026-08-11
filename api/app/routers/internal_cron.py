"""specs/02-architecture.md: no scheduler exists in this repo yet — an external scheduler
(a cron/launchd loop locally, EventBridge Scheduler in prod) hits these endpoints on an
interval. Shared-secret auth (app/auth/deps.py's require_internal_cron_secret), never
Cognito — there's no user behind a scheduled job. Not part of the public API surface:
excluded from the OpenAPI schema the web app's TS client is generated from.

Every handler here must sweep every org (a tick covers the whole platform, never a single
org context) and be safe to call again on the same tick if the caller retries after a
non-2xx.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from app.auth.deps import require_internal_cron_secret
from app.db.session import list_all_org_ids, org_session
from app.models.organization import Organization
from app.services.usage_service import aggregate_and_report_usage, check_usage_thresholds
from app.services.webhook_service import retry_pending_deliveries

router = APIRouter(
    prefix="/internal/cron",
    tags=["internal-cron"],
    include_in_schema=False,
    dependencies=[Depends(require_internal_cron_secret)],
)


@router.post("/webhook-retry")
async def webhook_retry_tick() -> dict:
    """Closes the Phase 3 gap noted in app/services/webhook_service.py's module
    docstring: retry_pending_deliveries() is real and correct but had no periodic caller
    until now."""
    now = datetime.now(UTC)
    retried_count = 0
    for org_id in await list_all_org_ids():
        async with org_session(org_id) as session:
            retried_count += len(await retry_pending_deliveries(session, org_id, now))
    return {"deliveries_retried": retried_count}


@router.post("/usage-aggregate")
async def usage_aggregate_tick() -> dict:
    """specs/09-admin-billing.md: "daily job aggregates usage_records -> Stripe meter
    events.\""""
    now = datetime.now(UTC)
    records_reported = 0
    for org_id in await list_all_org_ids():
        async with org_session(org_id) as session:
            records_reported += await aggregate_and_report_usage(session, org_id, now)
    return {"records_reported": records_reported}


@router.post("/usage-threshold-check")
async def usage_threshold_check_tick() -> dict:
    now = datetime.now(UTC)
    events_fired: dict[str, list[str]] = {}
    for org_id in await list_all_org_ids():
        async with org_session(org_id) as session:
            org = await session.get(Organization, org_id)
            if org is None:
                continue
            fired = await check_usage_thresholds(session, org, now)
            if fired:
                events_fired[org_id] = fired
    return {"events_fired": events_fired}
