"""app/auth/cognito.py's password_login() - the real (non-dev) sign-in path. Found
missing entirely while assessing pilot-readiness: the login page only ever called
POST /auth/dev-login, which 404s outside env=="local" - meaning no real Cognito user
could sign in at all, regardless of the app client's own OAuth/SRP config. See
ga_readiness_punchlist memory.

boto3 is mocked here (not "assume no AWS creds in CI") so this is deterministic
regardless of environment - the same reasoning as tests/test_ocr.py's Textract mocking.
"""

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from app.auth.cognito import password_login
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


def test_password_login_not_configured_raises_501() -> None:
    with pytest.raises(ApiError) as exc_info:
        password_login(Settings(env="local"), "a@example.com", "pw")
    assert exc_info.value.status_code == 501


def test_password_login_success_returns_id_token(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    fake_client.initiate_auth.return_value = {"AuthenticationResult": {"IdToken": "real-id-token"}}
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    token = password_login(_configured_settings(), "a@example.com", "correct-password")

    assert token == "real-id-token"
    fake_client.initiate_auth.assert_called_once_with(
        ClientId="client123",
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": "a@example.com", "PASSWORD": "correct-password"},
    )


@pytest.mark.parametrize("error_code", ["NotAuthorizedException", "UserNotFoundException"])
def test_password_login_wrong_credentials_returns_generic_401(monkeypatch: pytest.MonkeyPatch, error_code: str) -> None:
    fake_client = MagicMock()
    fake_client.initiate_auth.side_effect = ClientError(
        {"Error": {"Code": error_code, "Message": "nope"}}, "InitiateAuth"
    )
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    with pytest.raises(ApiError) as exc_info:
        password_login(_configured_settings(), "a@example.com", "wrong-password")
    assert exc_info.value.status_code == 401
    assert "Incorrect email or password" in exc_info.value.detail


def test_password_login_challenge_required_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    fake_client.initiate_auth.return_value = {"ChallengeName": "NEW_PASSWORD_REQUIRED", "Session": "abc"}
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    with pytest.raises(ApiError) as exc_info:
        password_login(_configured_settings(), "a@example.com", "temp-password")
    assert exc_info.value.status_code == 401
    assert "NEW_PASSWORD_REQUIRED" in exc_info.value.detail


def test_password_login_unexpected_client_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    fake_client.initiate_auth.side_effect = ClientError(
        {"Error": {"Code": "InternalErrorException", "Message": "boom"}}, "InitiateAuth"
    )
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    with pytest.raises(ClientError):
        password_login(_configured_settings(), "a@example.com", "pw")
