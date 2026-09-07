from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8)


class SignupResponse(BaseModel):
    user_id: str
    email: str
    verification_required: bool


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class DevLoginRequest(BaseModel):
    """Local-only: mints a dev JWT for an existing (or newly created) user, standing in for
    the Cognito hosted login flow until a user pool exists."""

    email: EmailStr
    name: str = "Dev User"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
