"""Requires a running Postgres (see docker-compose.yml: `docker compose up -d postgres`)
pointed to by TEST_DATABASE_URL, migrated to head before the suite runs (`make test` does both).
"""

import os

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.seed.starter_rule_packs import get_packs, get_rules, get_versions

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
    "webhook_deliveries", "webhook_subscriptions", "draft_rules", "manuals",
    "rules", "rule_set_versions", "rule_packs", "invoices",
]

_RULE_PACKS_TABLE = sa.table(
    "rule_packs",
    sa.column("id", sa.String), sa.column("org_id", sa.String), sa.column("name", sa.String),
    sa.column("description", sa.String), sa.column("category", sa.String), sa.column("status", sa.String),
)
_RULE_SET_VERSIONS_TABLE = sa.table(
    "rule_set_versions",
    sa.column("id", sa.String), sa.column("rule_pack_id", sa.String), sa.column("org_id", sa.String),
    sa.column("version", sa.Integer), sa.column("status", sa.String), sa.column("published_by", sa.String),
    sa.column("published_at", sa.DateTime(timezone=True)), sa.column("changelog", sa.String),
)
_RULES_TABLE = sa.table(
    "rules",
    sa.column("id", sa.String), sa.column("rule_set_version_id", sa.String), sa.column("org_id", sa.String),
    sa.column("rule_key", sa.String), sa.column("name", sa.String), sa.column("trigger_type", sa.String),
    sa.column("config", sa.JSON), sa.column("exemption_code_id", sa.String),
    sa.column("exemption_library_code", sa.String), sa.column("priority", sa.Integer),
    sa.column("confidence_policy", sa.String), sa.column("exclusions", sa.JSON), sa.column("scope", sa.String),
    sa.column("source_ref", sa.String), sa.column("status", sa.String),
)


async def _reseed_starter_rule_packs() -> None:
    """rule_packs (and its children) hold GLOBAL rows (org_id IS NULL) alongside
    org-owned ones — the one table in TENANT_TABLES that isn't purely tenant data.
    Postgres's `TRUNCATE ... CASCADE` wipes the whole table regardless of row FK value
    (unlike a scoped DELETE), so the global starter-pack seed migration 0008 inserts
    needs to be re-applied after every truncate or it's gone for the rest of the test
    session.

    This MUST run on a connection that has *never* called set_config('app.org_id', ...)
    — empirically verified (not assumed): `set_config(name, value, is_local=true)`
    leaves that connection's baseline at '' (empty string), not NULL, for the rest of
    its life once touched, even after the transaction that set it commits. The
    asymmetric RLS policy's WITH CHECK needs a genuine NULL to allow a global-row
    insert, so this uses its own NullPool engine (guaranteed-fresh physical connection,
    never reused from `db_session`'s pool, which by this point in the test run has
    almost certainly been tainted by some test's set_org() call) rather than the
    session the calling test used."""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session, session.begin():
            await session.execute(sa.insert(_RULE_PACKS_TABLE), get_packs())
            await session.execute(sa.insert(_RULE_SET_VERSIONS_TABLE), get_versions())
            await session.execute(sa.insert(_RULES_TABLE), get_rules())
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncSession:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
        await session.execute(text(f"TRUNCATE {', '.join(TENANT_TABLES)} CASCADE"))
        await session.commit()
    await _reseed_starter_rule_packs()


async def set_org(session: AsyncSession, org_id: str) -> None:
    """See app/db/session.py for why this uses set_config() and not `SET LOCAL ... = :param`."""
    await session.execute(text("SELECT set_config('app.org_id', :org_id, true)"), {"org_id": org_id})


async def set_user(session: AsyncSession, user_id: str) -> None:
    await session.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": user_id})
