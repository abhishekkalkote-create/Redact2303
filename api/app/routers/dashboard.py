from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_org_db, require_role
from app.schemas.dashboard import QueueSummary, ReviewerWorkload
from app.services.dashboard_service import get_queue_summary, get_team_queue

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary", response_model=QueueSummary)
async def get_dashboard_summary(db: AsyncSession = Depends(get_org_db)) -> QueueSummary:
    return QueueSummary(**await get_queue_summary(db, datetime.now(UTC)))


@router.get("/dashboard/team-queue", response_model=list[ReviewerWorkload])
async def get_dashboard_team_queue(
    db: AsyncSession = Depends(get_org_db),
    _membership=Depends(require_role("agency_admin", "supervisor")),
) -> list[ReviewerWorkload]:
    return [ReviewerWorkload(**w) for w in await get_team_queue(db, datetime.now(UTC))]
