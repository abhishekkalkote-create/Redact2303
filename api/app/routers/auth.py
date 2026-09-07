from fastapi import APIRouter, Depends

from app.auth.cognito import (
    confirm_forgot_password,
    confirm_sign_up,
    forgot_password,
    password_login,
    sign_up,
)
from app.auth.dev_provider import mint_dev_token
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.ids import new_id
from app.schemas.auth import (
    ConfirmSignupRequest,
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
    Hosted-UI/OAuth."""
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
    """Real Cognito `sign_up` - auto_verified_attributes=["email"] (infra/modules/cognito)
    means the account starts UNCONFIRMED and a verification code is emailed automatically;
    POST /auth/confirm-signup below completes it. No local `users` row is created here -
    app/auth/deps.py's _get_or_create_user lazily creates it on first authenticated
    request after the user logs in, same as every other auth path in this file."""
    user_id, needs_confirmation = sign_up(settings, payload.email, payload.name, payload.password)
    return SignupResponse(user_id=user_id, email=payload.email, verification_required=needs_confirmation)


@router.post("/confirm-signup", status_code=204)
async def confirm_signup(
    payload: ConfirmSignupRequest, settings: Settings = Depends(get_settings)
) -> None:
    confirm_sign_up(settings, payload.email, payload.code)


@router.post("/dev-login", response_model=TokenResponse)
async def dev_login(
    payload: DevLoginRequest, settings: Settings = Depends(get_settings)
) -> TokenResponse:
    if settings.env != "local" or not settings.dev_auth_enabled:
        raise ApiError(404, "Not Found")
    token = mint_dev_token(settings, sub=new_id("devsub"), email=payload.email, name=payload.name)
    return TokenResponse(access_token=token)
