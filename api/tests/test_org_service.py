"""app/services/org_service.py's create_org: focused test for the billing customer
provisioning added in Phase 5 slice 3 — org creation as a whole predates this repo's test
suite and isn't otherwise covered here.

create_org manages its own sessions (user_session/org_session) rather than taking one as
a parameter, so it goes through app/db/session.py's module-level AsyncSessionLocal
singleton — conftest.py's autouse _point_app_db_at_test_database fixture points that at
the test database for every test.
"""

import pytest
from sqlalchemy import text

from app.core.ids import new_id
from app.models.user import User
from app.schemas.organization import OrgCreate
from app.services.org_service import create_org


@pytest.mark.asyncio
async def test_create_org_provisions_a_billing_customer(db_session) -> None:
    user_id = new_id("usr")
    async with db_session.begin():
        await db_session.execute(
            text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active')"),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )

    owner = User(id=user_id, email=f"{user_id}@example.com", name=user_id)
    org = await create_org(owner, OrgCreate(name="Test Org", jurisdiction_state="WA", org_type="city_clerk"))

    assert org.stripe_customer_id is not None
    assert org.stripe_customer_id.startswith("cus_")
