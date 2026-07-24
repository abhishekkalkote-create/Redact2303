from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8)


class SignupResponse(BaseModel):
    user_id: str
    email: str
    verification_required: bool


class DevLoginRequest(BaseModel):
    """Local-only: mints a dev JWT for an existing (or newly created) user, standing in for
    the Cognito hosted login flow until a user pool exists."""

    email: EmailStr
    name: str = "Dev User"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
