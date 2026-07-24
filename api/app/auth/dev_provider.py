"""Local dev-only auth stand-in. NEVER active outside `env == "local"` (checked by callers,
not here, so a misconfigured deploy fails loud rather than silently accepting dev tokens).

Lets the org/membership/RLS flow be built and tested end-to-end before a Cognito user pool
exists — see specs/02-architecture.md ADR-7 for why Cognito is decoupled from authorization.
"""

import jwt

from app.auth.cognito import CognitoClaims
from app.core.config import Settings

ALGORITHM = "HS256"


def mint_dev_token(settings: Settings, sub: str, email: str, name: str) -> str:
    payload = {"sub": sub, "email": email, "name": name, "iss": settings.dev_auth_issuer}
    return jwt.encode(payload, settings.dev_auth_secret, algorithm=ALGORITHM)


def verify_dev_token(settings: Settings, token: str) -> CognitoClaims:
    payload = jwt.decode(
        token,
        settings.dev_auth_secret,
        algorithms=[ALGORITHM],
        issuer=settings.dev_auth_issuer,
    )
    return CognitoClaims(sub=payload["sub"], email=payload["email"], name=payload.get("name"))
