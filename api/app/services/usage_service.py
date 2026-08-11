"""specs/09-admin-billing.md § Metering + specs/04-api-spec.md § Usage, billing, audit.
Usage totals are computed live off usage_records (no stored snapshot) — same
on-demand-aggregation pattern as app/services/dashboard_service.py and
app/services/rule_service.py's get_rule_improvements_report.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.plans import PLAN_CATALOG
from app.billing.provider import get_billing_provider
from app.models.document import Document
from app.models.membership import Membership
from app.models.organization import Organization
from app.models.usage_record import UsageRecord
from app.models.user import User
from app.models.webhook import WebhookDelivery
from app.services.webhook_service import trigger_event

THRESHOLD_EVENTS = (("usage.threshold_95", 0.95), ("usage.threshold_80", 0.80))


def current_billing_period(now: datetime) -> str:
    return now.strftime("%Y-%m")


def _usage_window_conditions(org_id: str, metric: str, plan: str, now: datetime) -> list:
    """Pilot's cap is cumulative across the whole trial; Starter/Growth reset monthly
    (see app/billing/plans.py's cap_kind). Enterprise/custom has no fixed window at all —
    callers check `pages_included is not None` before using this."""
    conditions = [UsageRecord.org_id == org_id, UsageRecord.metric == metric]
    if PLAN_CATALOG[plan].cap_kind == "monthly":
        conditions.append(UsageRecord.billing_period == current_billing_period(now))
    return conditions


async def get_usage_current(session: AsyncSession, org: Organization, now: datetime) -> dict:
    catalog = PLAN_CATALOG[org.plan]
    period = current_billing_period(now)

    period_conditions = [UsageRecord.org_id == org.id]
    if catalog.cap_kind == "monthly":
        period_conditions.append(UsageRecord.billing_period == period)

    totals_result = await session.execute(
        select(UsageRecord.metric, func.sum(UsageRecord.quantity)).where(*period_conditions).group_by(UsageRecord.metric)
    )
    totals_by_metric = {metric: int(total) for metric, total in totals_result.all()}

    seats_active = (
        await session.execute(
            select(func.count()).select_from(Membership).where(Membership.org_id == org.id, Membership.status == "active")
        )
    ).scalar_one()

    pages_used = totals_by_metric.get("pages_processed", 0)
    pages_included = catalog.pages_included
    overage_pages = max(0, pages_used - pages_included) if pages_included is not None else 0
    overage_cost_cents = 0
    if overage_pages and catalog.overage_price_per_100_pages_cents:
        overage_units = -(-overage_pages // 100)  # ceil division: any partial 100 still bills a full unit
        overage_cost_cents = overage_units * catalog.overage_price_per_100_pages_cents

    per_user_result = await session.execute(
        select(Document.uploaded_by, User.name, func.sum(UsageRecord.quantity))
        .join(Document, UsageRecord.doc_id == Document.id)
        .join(User, User.id == Document.uploaded_by)
        .where(*_usage_window_conditions(org.id, "pages_processed", org.plan, now))
        .group_by(Document.uploaded_by, User.name)
        .order_by(func.sum(UsageRecord.quantity).desc())
    )
    per_user_breakdown = [
        {"user_id": user_id, "user_name": name, "pages_processed": int(qty)} for user_id, name, qty in per_user_result.all()
    ]

    return {
        "period": period,
        "plan": org.plan,
        "cap_kind": catalog.cap_kind,
        "totals_by_metric": totals_by_metric,
        "pages_included": pages_included,
        "pages_used": pages_used,
        "seats_included": catalog.seats_included,
        "seats_active": seats_active,
        "overage_pages": overage_pages,
        "overage_cost_cents": overage_cost_cents,
        "per_user_breakdown": per_user_breakdown,
    }


async def list_usage_records(session: AsyncSession, org_id: str, period: str | None) -> list[UsageRecord]:
    conditions = [UsageRecord.org_id == org_id]
    if period:
        conditions.append(UsageRecord.billing_period == period)
    result = await session.execute(select(UsageRecord).where(*conditions).order_by(UsageRecord.occurred_at.desc()))
    return list(result.scalars().all())


async def aggregate_and_report_usage(session: AsyncSession, org_id: str, now: datetime) -> int:
    """specs/09-admin-billing.md: "daily job aggregates usage_records -> Stripe meter
    events." Reports unreported records for the org's current period grouped by metric,
    then stamps reported_to_billing_at so a re-run of this tick never double-reports —
    same idempotency requirement as app/services/webhook_service.py's delivery retries."""
    org = await session.get(Organization, org_id)
    if org is None or not org.stripe_customer_id:
        return 0

    period = current_billing_period(now)
    result = await session.execute(
        select(UsageRecord).where(
            UsageRecord.org_id == org_id,
            UsageRecord.billing_period == period,
            UsageRecord.reported_to_billing_at.is_(None),
        )
    )
    records = list(result.scalars().all())
    if not records:
        return 0

    totals: dict[str, int] = {}
    for record in records:
        totals[record.metric] = totals.get(record.metric, 0) + record.quantity

    provider = get_billing_provider()
    for metric, quantity in totals.items():
        await provider.report_usage(org.stripe_customer_id, metric, quantity, period)

    for record in records:
        record.reported_to_billing_at = now
    await session.flush()
    return len(records)


async def check_usage_thresholds(session: AsyncSession, org: Organization, now: datetime) -> list[str]:
    """Fires usage.threshold_80/usage.threshold_95 at most once per threshold per billing
    period. "Already sent this period" is derived from webhook_deliveries' own history
    (has a delivery for this event existed since the period started?) rather than a
    dedicated column — the fact is already recorded there once a subscription exists;
    orgs with no matching subscription just harmlessly re-check every tick, since
    trigger_event no-ops when nothing is subscribed."""
    catalog = PLAN_CATALOG[org.plan]
    if catalog.pages_included is None:
        return []

    pages_used_result = await session.execute(
        select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
            *_usage_window_conditions(org.id, "pages_processed", org.plan, now)
        )
    )
    pages_used = pages_used_result.scalar_one()
    usage_ratio = pages_used / catalog.pages_included

    period_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    fired = []
    for event_type, threshold in THRESHOLD_EVENTS:
        if usage_ratio < threshold:
            continue
        already_sent = await session.execute(
            select(WebhookDelivery.id)
            .where(
                WebhookDelivery.org_id == org.id, WebhookDelivery.event == event_type,
                WebhookDelivery.created_at >= period_start,
            )
            .limit(1)
        )
        if already_sent.scalar_one_or_none() is not None:
            continue
        await trigger_event(
            session, org.id, event_type,
            {"pages_used": pages_used, "pages_included": catalog.pages_included, "usage_ratio": round(usage_ratio, 4)},
        )
        fired.append(event_type)
    return fired
