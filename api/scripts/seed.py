"""Phase 0 seed: a demo org + agency_admin membership for local dev/demo.

Usage: `python -m scripts.seed` (run from /api with the venv active, DATABASE_URL set).
"""

import asyncio

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.membership import Membership
from app.models.organization import DEFAULT_SETTINGS, Organization
from app.models.user import User

DEMO_ORG_ID = "org_demo0000000000000000000"
DEMO_USER_ID = "usr_demo0000000000000000000"
DEMO_EMAIL = "demo@redactproof.local"


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        org = await session.get(Organization, DEMO_ORG_ID)
        if org is None:
            org = Organization(
                id=DEMO_ORG_ID,
                name="Demo Records Office",
                slug="demo-records-office",
                jurisdiction_state="WA",
                org_type="city_clerk",
                settings=dict(DEFAULT_SETTINGS),
            )
            session.add(org)

        user = await session.get(User, DEMO_USER_ID)
        if user is None:
            user = User(id=DEMO_USER_ID, email=DEMO_EMAIL, name="Demo Admin")
            session.add(user)

        await session.flush()

        existing = await session.execute(
            select(Membership).where(
                Membership.org_id == DEMO_ORG_ID, Membership.user_id == DEMO_USER_ID
            )
        )
        if existing.scalar_one_or_none() is None:
            session.add(
                Membership(org_id=DEMO_ORG_ID, user_id=DEMO_USER_ID, role="agency_admin", status="active")
            )

        await session.commit()
    print(f"Seeded demo org {DEMO_ORG_ID} with admin user {DEMO_EMAIL}")


if __name__ == "__main__":
    asyncio.run(seed())
