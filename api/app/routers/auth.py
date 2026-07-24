from fastapi import APIRouter, Depends

from app.auth.dev_provider import mint_dev_token
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.ids import new_id
from app.schemas.auth import DevLoginRequest, SignupRequest, SignupResponse, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


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
