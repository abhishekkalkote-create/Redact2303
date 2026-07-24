from collections.abc import AsyncGenerator

import jwt as pyjwt
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.cognito import CognitoClaims, CognitoVerifier
from app.auth.dev_provider import verify_dev_token
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.db.session import AsyncSessionLocal, org_session, user_session
from app.models.membership import Membership
from app.models.user import User


def _unauthorized(detail: str) -> ApiError:
    return ApiError(401, "Unauthorized", detail)


def _verify_bearer_token(token: str, settings: Settings) -> CognitoClaims:
    if settings.env == "local" and settings.dev_auth_enabled:
        try:
            unverified = pyjwt.get_unverified_header(token)  # noqa: F841
            payload = pyjwt.decode(token, options={"verify_signature": False})
            if payload.get("iss") == settings.dev_auth_issuer:
                return verify_dev_token(settings, token)
        except pyjwt.PyJWTError:
            pass
    if not settings.cognito_configured:
        raise _unauthorized("No identity provider configured for this environment")
    return CognitoVerifier(settings).verify(token)


async def get_current_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> User:
    # Optional (not Header(...)) so OpenAPI doesn't mark this as a required per-call
    # parameter — that would force every generated TS client call site to pass it
    # explicitly, defeating the point of injecting it once via api-client's middleware
    # (web/src/lib/api-client.ts). The check below still makes it effectively required.
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized("Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        claims = _verify_bearer_token(token, settings)
    except pyjwt.PyJWTError as exc:
        raise _unauthorized("Invalid or expired token") from exc

    # Global users table has no RLS — plain session is correct here.
    async with AsyncSessionLocal() as session:
        user = await _get_or_create_user(session, claims)
        return user


async def _get_or_create_user(session: AsyncSession, claims: CognitoClaims) -> User:
    result = await session.execute(select(User).where(User.cognito_sub == claims.sub))
    user = result.scalar_one_or_none()
    if user is None:
        result = await session.execute(select(User).where(User.email == claims.email))
        user = result.scalar_one_or_none()
    if user is None:
        user = User(cognito_sub=claims.sub, email=claims.email, name=claims.name)
        session.add(user)
        await session.commit()
    elif user.cognito_sub is None:
        user.cognito_sub = claims.sub
        await session.commit()
    return user


async def get_current_org_id(x_org_id: str | None = Header(default=None, alias="X-Org-Id")) -> str | None:
    """Per specs/04-api-spec.md: org context comes from membership; multi-org users pass X-Org-Id."""
    return x_org_id


async def get_membership(
    user: User = Depends(get_current_user),
    org_id: str | None = Depends(get_current_org_id),
) -> Membership:
    """Looks up the caller's own membership(s) via `user_session` (see db/session.py) — a
    plain, no-context session can never see `memberships` rows at all under forced RLS, and
    `org_session` requires already knowing which org, which is exactly what this resolves."""
    async with user_session(user.id) as session:
        query = select(Membership).where(
            Membership.user_id == user.id, Membership.status != "deactivated"
        )
        if org_id:
            query = query.where(Membership.org_id == org_id)
        result = await session.execute(query.order_by(Membership.created_at))
        membership = result.scalars().first()
    if membership is None:
        raise ApiError(403, "Forbidden", "User has no active organization membership")
    return membership


async def get_org_db(
    membership: Membership = Depends(get_membership),
) -> AsyncGenerator[AsyncSession, None]:
    async with org_session(membership.org_id) as session:
        yield session


def require_role(*roles: str):
    async def _dep(membership: Membership = Depends(get_membership)) -> Membership:
        if membership.role not in roles:
            raise ApiError(403, "Forbidden", f"Requires one of roles: {', '.join(roles)}")
        return membership

    return _dep
