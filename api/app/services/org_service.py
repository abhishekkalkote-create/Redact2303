import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import ConflictError
from app.core.ids import new_id
from app.db.session import org_session, user_session
from app.models.membership import Membership
from app.models.organization import DEFAULT_SETTINGS, Organization
from app.models.user import User
from app.schemas.organization import OrgCreate

MAX_SLUG_ATTEMPTS = 5


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "org"


async def create_org(owner: User, payload: OrgCreate) -> Organization:
    """Creates the org and an active `agency_admin` membership for the creator, atomically.

    The org's id is generated up front (not left to the DB/ORM default) so we can declare
    `app.org_id` to that value *before* inserting — satisfying the same `id = app.org_id`
    RLS policy every other organizations write uses. No special-cased "org creation" policy
    needed: org creation just happens to be the one write where the actor gets to pick which
    org context to declare, because the row doesn't exist under any other context yet.

    Slug uniqueness can't be pre-checked with a SELECT: `organizations` RLS restricts SELECT
    to `id = app.org_id`, so a session with no org context yet can never see whether another
    org already has a given slug — it would always look free. Uniqueness is therefore enforced
    the only way that's actually correct here: attempt the insert, and on the DB's unique
    violation, retry with a suffixed slug (also closes the ordinary check-then-insert race
    that would exist even without RLS).
    """
    # "One active org per user" (specs/03-data-model.md) must be checked via `user_session`,
    # not a plain or org-scoped session — `memberships` RLS only ever exposes rows for
    # app.org_id or app.user_id; there is no org context yet, and org_id-scoping would only
    # ever see rows in a *specific* org, not "does this user belong to ANY org".
    async with user_session(owner.id) as session:
        existing = await session.execute(
            select(Membership).where(Membership.user_id == owner.id, Membership.status != "deactivated")
        )
        if existing.scalars().first() is not None:
            raise ConflictError("User already belongs to an organization (v1: one active org per user)")

    base_slug = _slugify(payload.name)

    for attempt in range(1, MAX_SLUG_ATTEMPTS + 1):
        slug = base_slug if attempt == 1 else f"{base_slug}-{attempt}"
        org_id = new_id("org")
        try:
            async with org_session(org_id) as org_scoped_session:
                org = Organization(
                    id=org_id,
                    name=payload.name,
                    slug=slug,
                    jurisdiction_state=payload.jurisdiction_state.upper(),
                    org_type=payload.org_type,
                    settings=dict(DEFAULT_SETTINGS),
                )
                org_scoped_session.add(org)
                # Flush the org row before adding the membership: without an ORM-level
                # relationship() between Membership and Organization (just a plain FK
                # column), SQLAlchemy's flush doesn't infer that the membership insert must
                # be ordered after the org insert — batching both into one flush() actually
                # sent the membership INSERT first and violated the FK. Two flushes fixes it.
                await org_scoped_session.flush()
                org_scoped_session.add(
                    Membership(org_id=org_id, user_id=owner.id, role="agency_admin", status="active")
                )
                await org_scoped_session.flush()
                await org_scoped_session.refresh(org)
                return org
        except IntegrityError as exc:
            if "uq" not in str(exc.orig).lower() and "slug" not in str(exc.orig).lower():
                raise
            continue

    raise ConflictError(f"Could not allocate a unique slug for '{payload.name}'")
