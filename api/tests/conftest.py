"""Requires a running Postgres (see docker-compose.yml: `docker compose up -d postgres`)
pointed to by TEST_DATABASE_URL, migrated to head before the suite runs (`make test` does both).
"""

import os

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://redactproof:redactproof@localhost:5432/redactproof_test"
)


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL)
    yield engine
    await engine.dispose()


# Tests deliberately open multiple separate `async with session.begin():` blocks (to
# simulate distinct request transactions with different org contexts) — each one commits
# immediately, so a single rollback-on-teardown does nothing. TRUNCATE instead: it isn't
# an RLS-governed row operation and (unlike DELETE) wasn't revoked on append-only tables,
# so this works without weakening the production append-only guarantee it's testing.
TENANT_TABLES = [
    "usage_records", "audit_events", "export_artifacts", "review_actions",
    "redaction_candidates", "manifests", "processing_jobs", "document_pages", "documents",
    "requests", "exemption_codes", "invites", "memberships", "organizations", "users",
]


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncSession:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
        await session.execute(text(f"TRUNCATE {', '.join(TENANT_TABLES)} CASCADE"))
        await session.commit()


async def set_org(session: AsyncSession, org_id: str) -> None:
    """See app/db/session.py for why this uses set_config() and not `SET LOCAL ... = :param`."""
    await session.execute(text("SELECT set_config('app.org_id', :org_id, true)"), {"org_id": org_id})


async def set_user(session: AsyncSession, user_id: str) -> None:
    await session.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": user_id})
