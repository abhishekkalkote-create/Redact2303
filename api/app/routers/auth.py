from fastapi import APIRouter, Depends

from app.auth.cognito import confirm_forgot_password, forgot_password, password_login
from app.auth.dev_provider import mint_dev_token
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.ids import new_id
from app.schemas.auth import (
    DevLoginRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    SignupRequest,
    SignupResponse,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, settings: Settings = Depends(get_settings)) -> TokenResponse:
    """Real Cognito sign-in (USER_PASSWORD_AUTH) - see app/auth/cognito.py's
    password_login() docstring for why this is the direct-password flow, not
    Hosted-UI/OAuth. Pilot onboarding today is admin-create-user + admin-set-user-password
    --permanent (see ga_readiness_punchlist memory) rather than self-serve signup."""
    token = password_login(settings, payload.email, payload.password)
    return TokenResponse(access_token=token)


@router.post("/forgot-password", status_code=202)
async def forgot_password_request(
    payload: ForgotPasswordRequest, settings: Settings = Depends(get_settings)
) -> dict[str, bool]:
    """The app client's prevent_user_existence_errors="ENABLED" (infra/modules/cognito)
    means Cognito's own forgot_password call already returns success for an unknown
    email instead of raising - so no need to catch-and-hide anything here ourselves."""
    forgot_password(settings, payload.email)
    return {"sent": True}


@router.post("/reset-password", status_code=204)
async def reset_password(
    payload: ResetPasswordRequest, settings: Settings = Depends(get_settings)
) -> None:
    confirm_forgot_password(settings, payload.email, payload.code, payload.new_password)


@router.post("/signup", response_model=SignupResponse)
async def signup(payload: SignupRequest, settings: Settings = Depends(get_settings)) -> SignupResponse:
    """Prod path calls Cognito `sign_up` (email verification via Cognito hosted flow).
    Real Cognito wiring lands once a user pool exists — see infra/modules/cognito and
    specs/02-architecture.md ADR-7. For now this validates the shape of the contract."""
    if not settings.cognito_configured:
        raise ApiError(
            501,
            "Not Implemented",
            "Cognito is not configured yet (COGNITO_USER_POOL_ID/APP_CLIENT_ID unset). "
            "Use POST /auth/dev-login in local dev until the Cognito user pool is created.",
        )
    raise ApiError(501, "Not Implemented", "Cognito sign_up wiring pending user pool creation")


@router.post("/dev-login", response_model=TokenResponse)
async def dev_login(
    payload: DevLoginRequest, settings: Settings = Depends(get_settings)
) -> TokenResponse:
    if settings.env != "local" or not settings.dev_auth_enabled:
        raise ApiError(404, "Not Found")
    token = mint_dev_token(settings, sub=new_id("devsub"), email=payload.email, name=payload.name)
    return TokenResponse(access_token=token)
