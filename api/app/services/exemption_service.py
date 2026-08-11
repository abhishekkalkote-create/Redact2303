from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.models.exemption_code import ExemptionCode, ExemptionLibrary


async def require_exemption_code_in_org(session: AsyncSession, exemption_code_id: str) -> ExemptionCode:
    """Security self-review finding: exemption_code_id arrives as client input at every
    candidate-write site (review_service.patch_candidate/create_manual_candidate/
    bulk_update_candidates, search_service.search_and_create_candidates) and was written
    straight into redaction_candidates.exemption_code_id with no ownership check.
    exemption_codes' FK constraint alone doesn't stop this — FK checks run as the table
    owner and are NOT RLS-filtered, so a valid id belonging to a DIFFERENT org would
    satisfy the FK and still get written. `session.get` here IS RLS-filtered (a normal
    org-scoped session, per every other read in this codebase) — a cross-org id returns
    None, same as it not existing at all, which is exactly the right signal: the caller
    can't tell the difference between "wrong org" and "doesn't exist" (specs/04-api-spec.md
    § Conventions: "never leak other tenants' existence")."""
    code = await session.get(ExemptionCode, exemption_code_id)
    if code is None:
        raise NotFoundError("Exemption code not found")
    return code


async def clone_library_for_org(session: AsyncSession, org_id: str, jurisdiction_state: str) -> list[ExemptionCode]:
    """specs/06-exemption-taxonomy.md: "Orgs choosing jurisdiction at onboarding get
    federal + their state library pre-cloned." `session` must already be org-scoped
    (app.org_id = org_id) — same convention as every other exemption_codes write."""
    result = await session.execute(
        select(ExemptionLibrary).where(
            (ExemptionLibrary.level == "federal") | (ExemptionLibrary.state == jurisdiction_state)
        )
    )
    library_rows = result.scalars().all()

    cloned = []
    for lib_row in library_rows:
        code = ExemptionCode(
            id=new_id("exc"),
            org_id=org_id,
            library_id=lib_row.id,
            code=lib_row.code,
            label=lib_row.label,
            statute_citation=lib_row.statute_citation,
            description=lib_row.description,
            guidance_url=lib_row.guidance_url,
            status="active",
        )
        session.add(code)
        cloned.append(code)
    await session.flush()
    return cloned


async def find_org_code_by_library_code(
    session: AsyncSession, org_id: str, library_code: str
) -> ExemptionCode | None:
    """Look up one of an org's cloned codes by its original library `code` (e.g. "b(6)",
    "TX-PII") — used by deterministic detection to pick which exemption code to attach."""
    result = await session.execute(
        select(ExemptionCode)
        .join(ExemptionLibrary, ExemptionCode.library_id == ExemptionLibrary.id)
        .where(ExemptionCode.org_id == org_id, ExemptionLibrary.code == library_code)
    )
    return result.scalars().first()
