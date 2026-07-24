import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_org_db
from app.schemas.audit import AuditEventOut
from app.services.audit_service import list_audit_events

router = APIRouter(tags=["audit"])


@router.get("/audit-events")
async def get_audit_events(
    db: AsyncSession = Depends(get_org_db),
    actor_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    object_type: str | None = Query(default=None),
    object_id: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    format: str = Query(default="json", pattern="^(json|csv)$"),
):
    """specs/04-api-spec.md GET /audit-events — the "Screen 7: Audit" filterable event
    stream (specs/07-ui-spec.md). `object_type=document&object_id=<id>` is also how the
    per-document timeline view is built — there's no separate document-scoped endpoint."""
    events = await list_audit_events(
        db, actor_id=actor_id, action=action, object_type=object_type,
        object_id=object_id, date_from=date_from, date_to=date_to,
    )

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "created_at", "actor_type", "actor_id", "action", "object_type", "object_id", "metadata"])
        for event in events:
            writer.writerow(
                [event.id, event.created_at.isoformat(), event.actor_type, event.actor_id or "",
                 event.action, event.object_type, event.object_id, event.metadata_]
            )
        return Response(
            content=buffer.getvalue(), media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit-events.csv"},
        )

    return [AuditEventOut.model_validate(event) for event in events]
