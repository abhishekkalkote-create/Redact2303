from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.membership import Membership
from app.models.user import User

NEW_STATUSES = ("uploaded",)
PROCESSING_STATUSES = ("scanning", "queued", "extracting", "detecting")
COMPLETED_STATUSES = ("review_complete", "approved", "exported")
INACTIVE_ASSIGNMENT_STATUSES = ("exported", "deleted", "error")

DUE_SOON_WINDOW = timedelta(days=3)


def _start_of_month(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def get_queue_summary(session: AsyncSession, now: datetime) -> dict:
    """specs/07-ui-spec.md screen 2 KPI row, scoped to documents created this month."""
    since = _start_of_month(now)
    result = await session.execute(
        select(Document.status, func.count(Document.id)).where(Document.created_at >= since).group_by(Document.status)
    )
    counts: dict[str, int] = {row[0]: row[1] for row in result.all()}

    return {
        "new": sum(counts.get(s, 0) for s in NEW_STATUSES),
        "processing": sum(counts.get(s, 0) for s in PROCESSING_STATUSES),
        "ready_for_review": counts.get("ready_for_review", 0),
        "in_review": counts.get("in_review", 0),
        "awaiting_approval": counts.get("awaiting_approval", 0),
        "completed": sum(counts.get(s, 0) for s in COMPLETED_STATUSES),
    }


async def get_team_queue(session: AsyncSession, now: datetime) -> list[dict]:
    """specs/07-ui-spec.md screen 2: "Team queue (supervisor: per-reviewer workload,
    aging, due dates)." Four aggregate queries regardless of member count, rather than
    one query per reviewer."""
    members_result = await session.execute(
        select(Membership, User).join(User, Membership.user_id == User.id).where(Membership.status == "active")
    )
    members = members_result.all()

    active = Document.status.notin_(INACTIVE_ASSIGNMENT_STATUSES) & Document.assignee_id.is_not(None)

    assigned_result = await session.execute(
        select(Document.assignee_id, func.count(Document.id)).where(active).group_by(Document.assignee_id)
    )
    assigned: dict[str | None, int] = {row[0]: row[1] for row in assigned_result.all()}

    overdue_result = await session.execute(
        select(Document.assignee_id, func.count(Document.id))
        .where(active, Document.due_date < now)
        .group_by(Document.assignee_id)
    )
    overdue: dict[str | None, int] = {row[0]: row[1] for row in overdue_result.all()}

    due_soon_result = await session.execute(
        select(Document.assignee_id, func.count(Document.id))
        .where(active, Document.due_date >= now, Document.due_date <= now + DUE_SOON_WINDOW)
        .group_by(Document.assignee_id)
    )
    due_soon: dict[str | None, int] = {row[0]: row[1] for row in due_soon_result.all()}

    return [
        {
            "user_id": user.id, "name": user.name, "email": user.email,
            "assigned_count": assigned.get(user.id, 0),
            "overdue_count": overdue.get(user.id, 0),
            "due_soon_count": due_soon.get(user.id, 0),
        }
        for _membership, user in members
    ]
