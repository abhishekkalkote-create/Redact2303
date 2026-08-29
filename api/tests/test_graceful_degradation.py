"""app/llm/provider.py's get_provider() and app/pipeline/malware_scan.py's get_scanner()
used to only degrade gracefully (no crash) when env == "local" - for any other
environment where Bedrock/clamd simply weren't configured yet, they built a real
provider that raised/threw on first real use instead. Found while assessing what's
needed before real pilot customers can use a non-local deployment; see
ga_readiness_punchlist memory."""

import logging

import pytest

from app.core.config import Settings
from app.llm.provider import DisabledLLMProvider, FakeLLMProvider, get_provider
from app.pipeline.malware_scan import ClamdScanner, DisabledScanner, NoOpScanner, get_scanner


def _settings(**overrides: object) -> Settings:
    defaults = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "certificate_signing_key": "a-real-secret",
        "internal_cron_secret": "another-real-secret",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_get_provider_local_unconfigured_uses_fake() -> None:
    provider = get_provider(_settings(env="local", bedrock_enabled=False))
    assert isinstance(provider, FakeLLMProvider)


def test_get_provider_non_local_unconfigured_degrades_instead_of_crashing() -> None:
    provider = get_provider(_settings(env="dev", bedrock_enabled=False))
    assert isinstance(provider, DisabledLLMProvider)
    response = provider.complete(system="s", user="u")
    assert response.text == '{"findings": []}'


def test_get_provider_bedrock_enabled_builds_real_provider_in_any_env() -> None:
    # Confirms the fix didn't accidentally start masking real Bedrock usage - it should
    # still attempt BedrockProvider (and still fail loudly on the placeholder model id,
    # same as before) once bedrock_enabled is true, local or not.
    with pytest.raises(RuntimeError, match="BEDROCK_MODEL_ID"):
        get_provider(_settings(env="dev", bedrock_enabled=True))
    with pytest.raises(RuntimeError, match="BEDROCK_MODEL_ID"):
        get_provider(_settings(env="local", bedrock_enabled=True))


def test_get_scanner_local_unconfigured_uses_noop() -> None:
    scanner = get_scanner(_settings(env="local", clamd_host=None))
    assert isinstance(scanner, NoOpScanner)


def test_get_scanner_non_local_unconfigured_degrades_instead_of_crashing(caplog: pytest.LogCaptureFixture) -> None:
    scanner = get_scanner(_settings(env="dev", clamd_host=None))
    assert isinstance(scanner, DisabledScanner)

    with caplog.at_level(logging.WARNING):
        result = scanner.scan(b"some file bytes")
    assert result.infected is False
    assert any("malware_scan.skipped_not_configured" in record.message for record in caplog.records)


def test_get_scanner_configured_builds_real_scanner_in_any_env() -> None:
    scanner = get_scanner(_settings(env="dev", clamd_host="clamav.internal", clamd_port=3310))
    assert isinstance(scanner, ClamdScanner)
