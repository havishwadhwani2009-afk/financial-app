"""Environment-based configuration. No secrets are committed; see .env.example."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://finapp:finapp@localhost:5432/finapp"
    cors_origins: str = "http://localhost:3000"
    # Admin endpoints (ingestion / forecast generation) are DISABLED unless this is set.
    admin_token: str | None = None
    rate_limit: str = "120/minute"

    # Provider credentials / identification
    fred_api_key: str | None = None  # free key: https://fred.stlouisfed.org/docs/api/api_key.html
    sec_user_agent: str = "FinIntel research-app contact@example.com"  # SEC requires a real contact
    alphavantage_api_key: str | None = None
    stooq_api_key: str | None = None

    # HTTP behaviour
    http_timeout_s: float = 20.0
    http_max_retries: int = 3

    # Staleness: a source is flagged stale beyond this many days since its latest observation
    price_stale_days: int = 5

    # Optional LLM (research assistant). Core app works without it.
    anthropic_api_key: str | None = None

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
