from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_org_db
from app.models.exemption_code import ExemptionCode, ExemptionLibrary
from app.schemas.document import ExemptionCodeOut

router = APIRouter(tags=["exemption-codes"])


@router.get("/exemption-codes", response_model=list[ExemptionCodeOut])
async def list_exemption_codes(db: AsyncSession = Depends(get_org_db)) -> list[ExemptionCodeOut]:
    """specs/04-api-spec.md GET /exemption-codes — the org's own taxonomy (already cloned
    from the federal + state library at org creation, see exemption_service.py).
    LEFT JOINs ExemptionLibrary for `level`/`state` — specs/07-ui-spec.md screen 6's
    taxonomy view groups by federal/state/org, and only the library row (not the org's
    own clone) carries that classification; a code with no `library_id` is itself an
    org-only custom code, i.e. the "org" group."""
    result = await db.execute(
        select(ExemptionCode, ExemptionLibrary.level, ExemptionLibrary.state)
        .outerjoin(ExemptionLibrary, ExemptionCode.library_id == ExemptionLibrary.id)
        .where(ExemptionCode.status == "active")
        .order_by(ExemptionCode.code)
    )
    return [
        ExemptionCodeOut(
            id=code.id, code=code.code, label=code.label, statute_citation=code.statute_citation,
            description=code.description, status=code.status, library_id=code.library_id,
            level=level, state=state,
        )
        for code, level, state in result.all()
    ]
