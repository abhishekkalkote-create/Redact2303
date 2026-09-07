"""app/auth/cognito.py's forgot_password()/confirm_forgot_password() - self-service
password recovery. Found missing entirely while sweeping for pilot-readiness gaps:
zero references to "forgot"/"reset password" anywhere in api/ or web/, meaning any
pilot user who forgot their password had no way to recover the account themselves.

boto3 is mocked here for the same reason as test_password_login.py - deterministic
regardless of environment/AWS creds in CI.
"""

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from app.auth.cognito import confirm_forgot_password, forgot_password
from app.core.config import Settings
from app.core.errors import ApiError


def _configured_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        certificate_signing_key="a-real-secret",
        internal_cron_secret="another-real-secret",
        cognito_user_pool_id="us-east-1_abc123",
        cognito_app_client_id="client123",
    )


def test_forgot_password_not_configured_raises_501() -> None:
    with pytest.raises(ApiError) as exc_info:
        forgot_password(Settings(env="local"), "a@example.com")
    assert exc_info.value.status_code == 501


def test_forgot_password_calls_cognito(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    forgot_password(_configured_settings(), "a@example.com")

    fake_client.forgot_password.assert_called_once_with(
        ClientId="client123", Username="a@example.com"
    )


def test_confirm_forgot_password_not_configured_raises_501() -> None:
    with pytest.raises(ApiError) as exc_info:
        confirm_forgot_password(Settings(env="local"), "a@example.com", "123456", "new-password")
    assert exc_info.value.status_code == 501


def test_confirm_forgot_password_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    confirm_forgot_password(_configured_settings(), "a@example.com", "123456", "new-password")

    fake_client.confirm_forgot_password.assert_called_once_with(
        ClientId="client123",
        Username="a@example.com",
        ConfirmationCode="123456",
        Password="new-password",
    )


@pytest.mark.parametrize(
    "error_code", ["CodeMismatchException", "ExpiredCodeException", "UserNotFoundException"]
)
def test_confirm_forgot_password_bad_code_returns_400(
    monkeypatch: pytest.MonkeyPatch, error_code: str
) -> None:
    fake_client = MagicMock()
    fake_client.confirm_forgot_password.side_effect = ClientError(
        {"Error": {"Code": error_code, "Message": "nope"}}, "ConfirmForgotPassword"
    )
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    with pytest.raises(ApiError) as exc_info:
        confirm_forgot_password(_configured_settings(), "a@example.com", "wrong", "new-password")
    assert exc_info.value.status_code == 400


def test_confirm_forgot_password_unexpected_client_error_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = MagicMock()
    fake_client.confirm_forgot_password.side_effect = ClientError(
        {"Error": {"Code": "InternalErrorException", "Message": "boom"}}, "ConfirmForgotPassword"
    )
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    with pytest.raises(ClientError):
        confirm_forgot_password(_configured_settings(), "a@example.com", "123456", "new-password")
