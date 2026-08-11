"""DB session helpers.

Non-negotiable invariant (see CLAUDE.md #1): every org-scoped query must run with
`app.org_id` set in the same transaction, so Postgres RLS enforces tenant isolation even if
a query forgets a WHERE org_id clause. `org_session`/`get_org_db` are the ONLY sanctioned
ways for org-scoped services/routers to get a session.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Plain session, no org context. Only for auth/health/platform-admin routes."""
    async with AsyncSessionLocal() as session:
        yield session


@asynccontextmanager
async def org_session(org_id: str) -> AsyncGenerator[AsyncSession, None]:
    """`async with org_session(org_id) as session:` — for direct use in services (outside
    FastAPI's DI). Uses `set_config(...)` rather than `SET LOCAL app.org_id = :org_id` —
    Postgres's `SET` statement does not accept bind parameters at all (a hard limitation,
    not driver-specific), so `set_config()` (a regular function call) is the only
    parameterized way to do this safely.

    Deliberately a real `@asynccontextmanager`, NOT a bare async generator driven by
    `async for ... : return` — breaking out of an `async for` early calls `aclose()`, which
    throws `GeneratorExit` at the `yield` inside `session.begin()`, causing a ROLLBACK instead
    of a commit. `@asynccontextmanager` (and FastAPI's own `Depends()` generator wrapping)
    both avoid this by resuming the generator normally rather than via `GeneratorExit`.
    """
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.org_id', :org_id, true)"), {"org_id": org_id}
        )
        yield session


async def get_org_session(org_id: str) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency form — Depends() wraps this generator with the same
    `contextlib.asynccontextmanager` semantics `org_session` uses directly, so it's
    equally safe from routers."""
    async with org_session(org_id) as session:
        yield session


@asynccontextmanager
async def user_session(user_id: str) -> AsyncGenerator[AsyncSession, None]:
    """`async with user_session(user_id) as session:` — declares `app.user_id` (never
    `app.org_id`), giving visibility into the caller's OWN `memberships` rows across every
    org via the `self_membership_lookup` RLS policy (migration 0001). This is how a user's
    org(s) are discovered in the first place — there is no other RLS-safe way to query
    memberships before you know which org to scope to."""
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": user_id}
        )
        yield session


@asynccontextmanager
async def system_session() -> AsyncGenerator[AsyncSession, None]:
    """`async with system_session() as session:` — declares `app.system_context` (never
    `app.org_id` or `app.user_id`), the ONLY thing that unlocks the additive
    `system_context_select` RLS policy on `organizations` (migration 0011). That policy
    grants read-only visibility into the org *directory* (which org ids exist) and nothing
    else — every other tenant table's strict tenant_isolation policy still denies all rows
    to a session with no `app.org_id` set, same as before.

    Exists for exactly one purpose: internal cron handlers
    (app/routers/internal_cron.py) that must loop `org_session(org_id)` over every org, and
    have no other RLS-safe way to learn what "every org" is. Never expose this to anything
    that isn't that trusted, shared-secret-gated internal path."""
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(text("SELECT set_config('app.system_context', 'true', true)"))
        yield session
