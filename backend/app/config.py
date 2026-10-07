from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IM_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://incident:incident@localhost:5432/incident"

    # Shared secret Alertmanager sends as a bearer token. Empty rejects every webhook call.
    webhook_token: str = ""

    oidc_issuer: str = "http://localhost:8080/realms/incident"
    oidc_audience: str = "incident-manager"
    # Defaults to the Keycloak certs endpoint under the issuer. Override when the API reaches
    # Keycloak on an internal hostname that differs from the public issuer URL.
    oidc_jwks_url: str = ""

    # Comma-separated label names. Alerts with equal values for these labels share an incident.
    group_by_labels: str = "alertname,service"

    public_url: str = "http://localhost:5174"
    cors_origins: str = ""

    slack_bot_token: str = ""
    telegram_bot_token: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "incidents@example.com"
    smtp_starttls: bool = True

    worker_poll_seconds: float = 5.0
    worker_metrics_port: int = 9100

    @property
    def jwks_url(self) -> str:
        return self.oidc_jwks_url or f"{self.oidc_issuer}/protocol/openid-connect/certs"

    @property
    def grouping_labels(self) -> list[str]:
        return _split(self.group_by_labels)

    @property
    def allowed_origins(self) -> list[str]:
        return _split(self.cors_origins)


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
