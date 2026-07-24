from pydantic import BaseModel


class QueueSummary(BaseModel):
    """specs/07-ui-spec.md screen 2 KPI row: "New / Processing / Ready for review /
    In review / Awaiting approval / Completed this month." """

    new: int
    processing: int
    ready_for_review: int
    in_review: int
    awaiting_approval: int
    completed: int


class ReviewerWorkload(BaseModel):
    """specs/07-ui-spec.md screen 2: "Team queue (supervisor: per-reviewer workload,
    aging, due dates)." """

    user_id: str
    name: str
    email: str
    assigned_count: int
    overdue_count: int
    due_soon_count: int
