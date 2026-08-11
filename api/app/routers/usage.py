"""specs/04-api-spec.md § Usage, billing, audit."""

import csv
import io
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_membership, get_org_db
from app.models.membership import Membership
from app.models.organization import Organization
from app.schemas.usage import UsageCurrentOut, UsageRecordOut
from app.services.usage_service import get_usage_current, list_usage_records

router = APIRouter(tags=["usage"])


async def _get_current_org(db: AsyncSession, membership: Membership) -> Organization:
    org = await db.get(Organization, membership.org_id)
    # Same invariant as app/routers/orgs.py's _get_current_org: membership.org_id is
    # FK-constrained and both rows are read under the same org context.
    assert org is not None, f"membership {membership.id} references a missing org"
    return org


@router.get("/usage/current", response_model=UsageCurrentOut)
async def get_current_usage(
    membership: Membership = Depends(get_membership), db: AsyncSession = Depends(get_org_db)
) -> UsageCurrentOut:
    org = await _get_current_org(db, membership)
    return UsageCurrentOut(**await get_usage_current(db, org, datetime.now(UTC)))


@router.get("/usage/records")
async def get_usage_records(
    membership: Membership = Depends(get_membership),
    db: AsyncSession = Depends(get_org_db),
    period: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    format: str = Query(default="json", pattern="^(json|csv)$"),
):
    records = await list_usage_records(db, membership.org_id, period)

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "metric", "quantity", "doc_id", "job_id", "occurred_at", "billing_period"])
        for record in records:
            writer.writerow(
                [record.id, record.metric, record.quantity, record.doc_id or "", record.job_id or "",
                 record.occurred_at.isoformat(), record.billing_period]
            )
        return Response(
            content=buffer.getvalue(), media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=usage-records.csv"},
        )

    return [UsageRecordOut.model_validate(r) for r in records]
