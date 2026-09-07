"""Cognito JWT verification (specs/02-architecture.md ADR-7: Cognito authenticates only;
roles/memberships live in our DB). Verifies signature via the pool's JWKS, then issuer + audience.
"""

import jwt
from jwt import PyJWKClient

from app.core.config import Settings
from app.core.errors import ApiError


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


def password_login(settings: Settings, email: str, password: str) -> str:
    """USER_PASSWORD_AUTH (infra/modules/cognito's app client enables it alongside SRP) -
    deliberately not the Hosted-UI/OAuth-code flow the client is also configured for
    (`allowed_oauth_flows = ["code"]`): that needs a real callback-URL/domain story this
    app doesn't have yet (see ga_readiness_punchlist memory), while a direct
    email+password call needs none of that and is enough for a pilot's login form.

    Returns the ID token (not the access token) - CognitoVerifier.verify() above expects
    an `email` claim and an `aud` matching the app client id, which is the ID token's
    shape, not the access token's.
    """
    if not settings.cognito_configured:
        raise ApiError(501, "Not Implemented", "Cognito is not configured yet")

    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("cognito-idp", region_name=settings.cognito_region)
    try:
        response = client.initiate_auth(
            ClientId=settings.cognito_app_client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": email, "PASSWORD": password},
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NotAuthorizedException", "UserNotFoundException"):
            raise ApiError(401, "Unauthorized", "Incorrect email or password") from exc
        raise

    if "ChallengeName" in response:
        # NEW_PASSWORD_REQUIRED (admin-created users' temp password) or
        # SOFTWARE_TOKEN_MFA (a user who's set up TOTP) - the pilot onboarding runbook
        # sets a permanent password via admin-set-user-password so real pilot users
        # never hit the first one, and MFA is optional (not required) so nobody hits
        # the second unless they opted in. Surfacing this instead of crashing either
        # way, since "onboarding avoids it" isn't the same as "it can't happen."
        raise ApiError(
            401, "Unauthorized",
            f"Additional sign-in step required ({response['ChallengeName']}) - not supported by this login form yet.",
        )

    result = response.get("AuthenticationResult")
    if not result or "IdToken" not in result:
        raise ApiError(401, "Unauthorized", "Sign-in did not complete")
    id_token: str = result["IdToken"]
    return id_token


def sign_up(settings: Settings, email: str, name: str, password: str) -> tuple[str, bool]:
    """Self-serve registration. auto_verified_attributes=["email"] (infra/modules/cognito)
    means Cognito auto-sends a verification code on sign_up and the account starts
    UNCONFIRMED until confirm_sign_up() below completes - no separate "verify your email"
    step to build beyond that confirmation screen.

    `name` goes into the standard `name` attribute so CognitoClaims.name (cognito.py's
    verify()) has something real instead of falling back to the email address.

    Returns (user_sub, needs_confirmation) - needs_confirmation is False only in the
    (here, never-hit-in-practice) case a pool has email auto-confirm configured, so the
    router can still report the field honestly rather than hardcoding True.
    """
    if not settings.cognito_configured:
        raise ApiError(501, "Not Implemented", "Cognito is not configured yet")

    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("cognito-idp", region_name=settings.cognito_region)
    try:
        response = client.sign_up(
            ClientId=settings.cognito_app_client_id,
            Username=email,
            Password=password,
            UserAttributes=[{"Name": "email", "Value": email}, {"Name": "name", "Value": name}],
        )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "UsernameExistsException":
            # prevent_user_existence_errors="ENABLED" (infra/modules/cognito) only covers
            # initiate_auth/forgot_password - sign_up itself still raises this plainly, so
            # unlike those two flows this one genuinely does need to decide what to reveal.
            # Match forgot_password's already-established "don't reveal existence" stance
            # rather than leaking a distinguishable error here.
            raise ApiError(
                400, "Bad Request",
                "Could not create account with that email - it may already be registered.",
            ) from exc
        if error_code == "InvalidPasswordException":
            raise ApiError(400, "Bad Request", "Password does not meet the account policy") from exc
        raise
    return response["UserSub"], not response["UserConfirmed"]


def confirm_sign_up(settings: Settings, email: str, code: str) -> None:
    if not settings.cognito_configured:
        raise ApiError(501, "Not Implemented", "Cognito is not configured yet")

    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("cognito-idp", region_name=settings.cognito_region)
    try:
        client.confirm_sign_up(
            ClientId=settings.cognito_app_client_id,
            Username=email,
            ConfirmationCode=code,
        )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in ("CodeMismatchException", "ExpiredCodeException", "UserNotFoundException"):
            raise ApiError(400, "Bad Request", "Invalid or expired confirmation code") from exc
        if error_code == "NotAuthorizedException":
            # Cognito's own message for "already confirmed" - surfaced as-is since it's
            # actionable for the user (go sign in instead) rather than a generic 400.
            raise ApiError(400, "Bad Request", "This account is already confirmed") from exc
        raise


def forgot_password(settings: Settings, email: str) -> None:
    """Cognito's own default email delivery (COGNITO_DEFAULT - infra/modules/cognito's
    user pool sets no `email_configuration`, so this is the AWS default, not something
    that needs SES/SMTP wired up separately) sends the reset code. prevent_user_existence_errors
    ="ENABLED" on the app client means Cognito itself already declines to reveal whether
    the email exists - nothing extra to do here for that."""
    if not settings.cognito_configured:
        raise ApiError(501, "Not Implemented", "Cognito is not configured yet")

    import boto3

    client = boto3.client("cognito-idp", region_name=settings.cognito_region)
    client.forgot_password(ClientId=settings.cognito_app_client_id, Username=email)


def confirm_forgot_password(settings: Settings, email: str, code: str, new_password: str) -> None:
    if not settings.cognito_configured:
        raise ApiError(501, "Not Implemented", "Cognito is not configured yet")

    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("cognito-idp", region_name=settings.cognito_region)
    try:
        client.confirm_forgot_password(
            ClientId=settings.cognito_app_client_id,
            Username=email,
            ConfirmationCode=code,
            Password=new_password,
        )
    except ClientError as exc:
        code_name = exc.response.get("Error", {}).get("Code", "")
        if code_name in ("CodeMismatchException", "ExpiredCodeException", "UserNotFoundException"):
            raise ApiError(400, "Bad Request", "Invalid or expired reset code") from exc
        raise
