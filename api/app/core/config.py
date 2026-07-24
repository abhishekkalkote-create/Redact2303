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

    @property
    def cognito_configured(self) -> bool:
        return bool(self.cognito_user_pool_id and self.cognito_app_client_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
