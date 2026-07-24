"""Cognito JWT verification (specs/02-architecture.md ADR-7: Cognito authenticates only;
roles/memberships live in our DB). Verifies signature via the pool's JWKS, then issuer + audience.
"""

import jwt
from jwt import PyJWKClient

from app.core.config import Settings


class CognitoClaims:
    def __init__(self, sub: str, email: str, name: str | None = None) -> None:
        self.sub = sub
        self.email = email
        self.name = name or email


class CognitoVerifier:
    def __init__(self, settings: Settings) -> None:
        if not settings.cognito_configured:
            raise RuntimeError("Cognito is not configured (COGNITO_USER_POOL_ID/APP_CLIENT_ID)")
        self.issuer = (
            f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
            f"{settings.cognito_user_pool_id}"
        )
        self.audience = settings.cognito_app_client_id
        self._jwk_client = PyJWKClient(f"{self.issuer}/.well-known/jwks.json")

    def verify(self, token: str) -> CognitoClaims:
        signing_key = self._jwk_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=self.audience,
            issuer=self.issuer,
        )
        return CognitoClaims(
            sub=payload["sub"], email=payload["email"], name=payload.get("name")
        )
