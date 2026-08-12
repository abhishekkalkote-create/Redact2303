from functools import lru_cache
from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Security self-review finding: dev_auth_secret and local_dev_encryption_key are already
# unreachable outside env == "local" by construction (auth/deps.py only consults
# dev_auth_secret when env == "local"; crypto/envelope.py's get_cipher() never selects
# LocalDevCipher outside "local"). certificate_signing_key and internal_cron_secret have
# no equivalent code-level gate — Settings._forbid_insecure_defaults_outside_local below
# is that gate, failing loud at startup instead of silently running a prod deploy with a
# publicly-known signing key / cron secret.
_INSECURE_DEFAULTS = {
    "certificate_signing_key": "dev-only-insecure-certificate-signing-key-change-me",
    "internal_cron_secret": "dev-only-insecure-cron-secret-change-me",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "local"  # local | dev | staging | prod
    app_name: str = "RedactProof API"
    api_v1_prefix: str = "/v1"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://redactproof:redactproof@localhost:5432/redactproof"

    aws_region: str = "us-east-1"

    cognito_user_pool_id: str | None = None
    cognito_app_client_id: str | None = None
    cognito_region: str = "us-east-1"

    # Local-only dev auth (never enabled outside env == "local"); lets the team build and
    # test the org/membership/RLS flow before a Cognito user pool exists.
    dev_auth_enabled: bool = True
    dev_auth_issuer: str = "redactproof-dev"
    dev_auth_secret: str = "dev-only-insecure-secret-change-me"

    cors_origins: list[str] = ["http://localhost:3000"]

    # Local-only stand-in for per-org KMS envelope encryption (app/crypto/envelope.py).
    # This exact key is committed and public — it protects nothing. Never used outside
    # env == "local"; real per-org CMKs take over once an AWS account exists.
    local_dev_encryption_key: str = "qyhZRwVqQiUw1yI10p7u_P3YQQajwHwBzoT8Cmhkczk="

    # Local filesystem root standing in for the S3 content bucket (app/storage/*.py)
    # until infra/modules/storage is applied against a real AWS account.
    local_storage_root: str = "./.local-storage"
    s3_content_bucket: str | None = None

    # app/pipeline/malware_scan.py — unset means "use NoOpScanner" in local dev.
    clamd_host: str | None = None
    clamd_port: int = 3310

    max_upload_size_bytes: int = 500 * 1024 * 1024  # specs/01-product-spec.md US-1: 500MB single-file cap
    max_zip_upload_size_bytes: int = 2 * 1024 * 1024 * 1024  # US-1: 2GB ZIP batch cap

    # app/llm/provider.py — false means "use FakeLLMProvider" in local dev (no AWS
    # Bedrock account with model access exists yet).
    bedrock_enabled: bool = False
    bedrock_model_id: str | None = None

    # app/billing/provider.py — false means "use MockBillingProvider" in local dev (no
    # Stripe test-mode credentials exist yet).
    stripe_enabled: bool = False

    # app/pipeline/export.py's redaction certificate HMAC — real prod value belongs in
    # Secrets Manager (specs/02-architecture.md), not committed. This placeholder is
    # public and protects nothing.
    certificate_signing_key: str = "dev-only-insecure-certificate-signing-key-change-me"

    # app/routers/internal_cron.py — shared secret for the external scheduler (a cron/
    # launchd loop locally, EventBridge Scheduler in prod) that calls these endpoints;
    # there is no user behind a scheduled job, so this isn't a Cognito/JWT concern. Real
    # prod value belongs in Secrets Manager, not committed. This placeholder is public
    # and protects nothing.
    internal_cron_secret: str = "dev-only-insecure-cron-secret-change-me"

    @model_validator(mode="after")
    def _forbid_insecure_defaults_outside_local(self) -> Self:
        if self.env != "local":
            for field, default in _INSECURE_DEFAULTS.items():
                if getattr(self, field) == default:
                    raise ValueError(
                        f"{field} is still the checked-in insecure default outside env=='local' — "
                        f"set a real value via the {field.upper()} environment variable before deploying."
                    )
        return self

    @property
    def cognito_configured(self) -> bool:
        return bool(self.cognito_user_pool_id and self.cognito_app_client_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
