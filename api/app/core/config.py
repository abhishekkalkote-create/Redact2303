from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "local"  # local | dev | staging | prod
    app_name: str = "RedactProof API"
    api_v1_prefix: str = "/v1"

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

    # app/llm/provider.py — false means "use FakeLLMProvider" in local dev (no AWS
    # Bedrock account with model access exists yet).
    bedrock_enabled: bool = False
    bedrock_model_id: str | None = None

    # app/pipeline/export.py's redaction certificate HMAC — real prod value belongs in
    # Secrets Manager (specs/02-architecture.md), not committed. This placeholder is
    # public and protects nothing.
    certificate_signing_key: str = "dev-only-insecure-certificate-signing-key-change-me"

    @property
    def cognito_configured(self) -> bool:
        return bool(self.cognito_user_pool_id and self.cognito_app_client_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
