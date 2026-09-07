"""app/auth/cognito.py's sign_up()/confirm_sign_up() - self-serve registration. Built
2026-09-07 after deciding to bring this forward from the "deferred until >25 users"
punch-list item (see ga_readiness_punchlist memory) - AWS cost turned out to be a
non-issue (Cognito bills per-MAU regardless of creation method), so the only real
blocker was build effort, not spend.

boto3 is mocked here for the same reason as test_password_login.py/test_password_reset.py
- deterministic regardless of environment/AWS creds in CI.
"""

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from app.auth.cognito import confirm_sign_up, sign_up
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


def test_sign_up_not_configured_raises_501() -> None:
    with pytest.raises(ApiError) as exc_info:
        sign_up(Settings(env="local"), "a@example.com", "Jane Analyst", "correct-password")
    assert exc_info.value.status_code == 501


def test_sign_up_success_returns_sub_and_needs_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    fake_client.sign_up.return_value = {"UserSub": "sub-123", "UserConfirmed": False}
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    user_id, needs_confirmation = sign_up(
        _configured_settings(), "a@example.com", "Jane Analyst", "correct-password"
    )

    assert user_id == "sub-123"
    assert needs_confirmation is True
    fake_client.sign_up.assert_called_once_with(
        ClientId="client123",
        Username="a@example.com",
        Password="correct-password",
        UserAttributes=[
            {"Name": "email", "Value": "a@example.com"},
            {"Name": "name", "Value": "Jane Analyst"},
        ],
    )


def test_sign_up_already_confirmed_reports_no_confirmation_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    fake_client.sign_up.return_value = {"UserSub": "sub-456", "UserConfirmed": True}
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    _, needs_confirmation = sign_up(_configured_settings(), "a@example.com", "Jane", "correct-password")

    assert needs_confirmation is False


def test_sign_up_existing_email_does_not_leak_existence(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    fake_client.sign_up.side_effect = ClientError(
        {"Error": {"Code": "UsernameExistsException", "Message": "nope"}}, "SignUp"
    )
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    with pytest.raises(ApiError) as exc_info:
        sign_up(_configured_settings(), "a@example.com", "Jane", "correct-password")
    assert exc_info.value.status_code == 400
    assert "already be registered" in exc_info.value.detail


def test_sign_up_weak_password_returns_400(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    fake_client.sign_up.side_effect = ClientError(
        {"Error": {"Code": "InvalidPasswordException", "Message": "too weak"}}, "SignUp"
    )
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    with pytest.raises(ApiError) as exc_info:
        sign_up(_configured_settings(), "a@example.com", "Jane", "weak")
    assert exc_info.value.status_code == 400


def test_sign_up_unexpected_client_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    fake_client.sign_up.side_effect = ClientError(
        {"Error": {"Code": "InternalErrorException", "Message": "boom"}}, "SignUp"
    )
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    with pytest.raises(ClientError):
        sign_up(_configured_settings(), "a@example.com", "Jane", "correct-password")


def test_confirm_sign_up_not_configured_raises_501() -> None:
    with pytest.raises(ApiError) as exc_info:
        confirm_sign_up(Settings(env="local"), "a@example.com", "123456")
    assert exc_info.value.status_code == 501


def test_confirm_sign_up_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    confirm_sign_up(_configured_settings(), "a@example.com", "123456")

    fake_client.confirm_sign_up.assert_called_once_with(
        ClientId="client123", Username="a@example.com", ConfirmationCode="123456"
    )


@pytest.mark.parametrize(
    "error_code", ["CodeMismatchException", "ExpiredCodeException", "UserNotFoundException"]
)
def test_confirm_sign_up_bad_code_returns_400(monkeypatch: pytest.MonkeyPatch, error_code: str) -> None:
    fake_client = MagicMock()
    fake_client.confirm_sign_up.side_effect = ClientError(
        {"Error": {"Code": error_code, "Message": "nope"}}, "ConfirmSignUp"
    )
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    with pytest.raises(ApiError) as exc_info:
        confirm_sign_up(_configured_settings(), "a@example.com", "wrong")
    assert exc_info.value.status_code == 400


def test_confirm_sign_up_already_confirmed_returns_400(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    fake_client.confirm_sign_up.side_effect = ClientError(
        {"Error": {"Code": "NotAuthorizedException", "Message": "already confirmed"}}, "ConfirmSignUp"
    )
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    with pytest.raises(ApiError) as exc_info:
        confirm_sign_up(_configured_settings(), "a@example.com", "123456")
    assert exc_info.value.status_code == 400
    assert "already confirmed" in exc_info.value.detail


def test_confirm_sign_up_unexpected_client_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    fake_client.confirm_sign_up.side_effect = ClientError(
        {"Error": {"Code": "InternalErrorException", "Message": "boom"}}, "ConfirmSignUp"
    )
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake_client)

    with pytest.raises(ClientError):
        confirm_sign_up(_configured_settings(), "a@example.com", "123456")
