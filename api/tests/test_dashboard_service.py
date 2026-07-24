"""specs/07-ui-spec.md screen 2: Dashboard KPI row and the supervisor "Team queue" tab
(per-reviewer workload, aging, due dates)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.models.document import Document
from app.models.membership import Membership
from app.services.dashboard_service import get_queue_summary, get_team_queue
from tests.conftest import set_org


async def _seed_org(session: AsyncSession, org_id: str) -> None:
    await set_org(session, org_id)
    await session.execute(
        text(
            "INSERT INTO organizations (id, name, slug, jurisdiction_state, org_type, "
            "plan, plan_status, settings) VALUES "
            "(:id, :id, :id, 'WA', 'other', 'pilot', 'trialing', '{}')"
        ),
        {"id": org_id},
    )


async def _seed_user_and_membership(session: AsyncSession, org_id: str, user_id: str, role: str) -> None:
    await session.execute(
        text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active')"),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )
    session.add(Membership(id=new_id("mem"), org_id=org_id, user_id=user_id, role=role, status="active"))


def _doc(org_id: str, user_id: str, status: str, *, assignee_id: str | None = None, due_date=None, created_at=None) -> Document:
    return Document(
        id=new_id("doc"), org_id=org_id, filename="f.pdf", mime_type="application/pdf",
        source="upload", status=status, uploaded_by=user_id, content_sha256="x",
        assignee_id=assignee_id, due_date=due_date,
        **({"created_at": created_at} if created_at is not None else {}),
    )


@pytest.mark.asyncio
async def test_get_queue_summary_buckets_by_status_this_month(db_session: AsyncSession) -> None:
    org_id, user_id = "org_dash_1", "usr_dash_1"
    now = datetime(2026, 7, 24, tzinfo=UTC)

    async with db_session.begin():
        await _seed_org(db_session, org_id)
        await _seed_user_and_membership(db_session, org_id, user_id, "reviewer")

    async with db_session.begin():
        await set_org(db_session, org_id)
        db_session.add_all(
            [
                _doc(org_id, user_id, "uploaded", created_at=now),
                _doc(org_id, user_id, "queued", created_at=now),
                _doc(org_id, user_id, "extracting", created_at=now),
                _doc(org_id, user_id, "ready_for_review", created_at=now),
                _doc(org_id, user_id, "in_review", created_at=now),
                _doc(org_id, user_id, "awaiting_approval", created_at=now),
                _doc(org_id, user_id, "review_complete", created_at=now),
                _doc(org_id, user_id, "exported", created_at=now),
                # Last month — must not be counted in "this month"'s KPIs.
                _doc(org_id, user_id, "uploaded", created_at=now.replace(month=now.month - 1)),
            ]
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        summary = await get_queue_summary(db_session, now)

    assert summary["new"] == 1
    assert summary["processing"] == 2
    assert summary["ready_for_review"] == 1
    assert summary["in_review"] == 1
    assert summary["awaiting_approval"] == 1
    assert summary["completed"] == 2


@pytest.mark.asyncio
async def test_get_team_queue_workload_and_aging(db_session: AsyncSession) -> None:
    org_id = "org_dash_2"
    reviewer_a, reviewer_b = "usr_dash_a", "usr_dash_b"
    now = datetime(2026, 7, 24, tzinfo=UTC)

    async with db_session.begin():
        await _seed_org(db_session, org_id)
        await _seed_user_and_membership(db_session, org_id, reviewer_a, "reviewer")
        await _seed_user_and_membership(db_session, org_id, reviewer_b, "reviewer")

    async with db_session.begin():
        await set_org(db_session, org_id)
        db_session.add_all(
            [
                # Reviewer A: 1 overdue, 1 due-soon, 1 with no due date — 3 assigned total.
                _doc(org_id, reviewer_a, "in_review", assignee_id=reviewer_a, due_date=now - timedelta(days=1)),
                _doc(org_id, reviewer_a, "in_review", assignee_id=reviewer_a, due_date=now + timedelta(days=1)),
                _doc(org_id, reviewer_a, "in_review", assignee_id=reviewer_a, due_date=None),
                # Reviewer B: nothing assigned.
                # An exported doc assigned to A must NOT count — it's no longer active work.
                _doc(org_id, reviewer_a, "exported", assignee_id=reviewer_a, due_date=now - timedelta(days=10)),
            ]
        )

    async with db_session.begin():
        await set_org(db_session, org_id)
        workload = await get_team_queue(db_session, now)

    by_user = {w["user_id"]: w for w in workload}
    assert by_user[reviewer_a]["assigned_count"] == 3
    assert by_user[reviewer_a]["overdue_count"] == 1
    assert by_user[reviewer_a]["due_soon_count"] == 1
    assert by_user[reviewer_b]["assigned_count"] == 0
    assert by_user[reviewer_b]["overdue_count"] == 0
