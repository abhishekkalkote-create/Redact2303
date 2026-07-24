from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_org_db
from app.models.exemption_code import ExemptionCode
from app.schemas.document import ExemptionCodeOut

router = APIRouter(tags=["exemption-codes"])


@router.get("/exemption-codes", response_model=list[ExemptionCodeOut])
async def list_exemption_codes(db: AsyncSession = Depends(get_org_db)) -> list[ExemptionCode]:
    """specs/04-api-spec.md GET /exemption-codes — the org's own taxonomy (already cloned
    from the federal + state library at org creation, see exemption_service.py)."""
    result = await db.execute(
        select(ExemptionCode).where(ExemptionCode.status == "active").order_by(ExemptionCode.code)
    )
    return list(result.scalars().all())
