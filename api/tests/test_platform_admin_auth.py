"""app/auth/deps.py's require_platform_admin: the one thing worth proving through the
REAL auth stack (mint_dev_token -> get_current_user -> platform_admins lookup) rather
than a hand-built dependency call — this is the first test in this suite to exercise
that flow end-to-end, using app/auth/dev_provider.py's own token-minting utility rather
than anything hand-rolled.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dev_provider import mint_dev_token
from app.core.config import get_settings
from app.core.ids import new_id
from app.main import app


async def _create_user(session: AsyncSession, user_id: str) -> str:
    await session.execute(
        text("INSERT INTO users (id, email, name, status) VALUES (:id, :email, :id, 'active')"),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )
    return mint_dev_token(get_settings(), sub=user_id, email=f"{user_id}@example.com", name=user_id)


@pytest.mark.asyncio
async def test_platform_route_requires_a_bearer_token() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/platform/orgs")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_platform_route_rejects_an_ordinary_user(db_session: AsyncSession) -> None:
    async with db_session.begin():
        token = await _create_user(db_session, new_id("usr"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/platform/orgs", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_platform_route_allows_a_platform_admin(db_session: AsyncSession) -> None:
    user_id = new_id("usr")
    async with db_session.begin():
        token = await _create_user(db_session, user_id)
        await db_session.execute(
            text("INSERT INTO platform_admins (user_id, permissions) VALUES (:id, '{}')"), {"id": user_id}
        )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/platform/orgs", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
