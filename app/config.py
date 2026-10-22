from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# the app talks to the DB asynchronously, so plain URLs get an async driver
_ASYNC_DRIVERS = {"sqlite://": "sqlite+aiosqlite://", "postgresql://": "postgresql+psycopg://"}


class KeitaroSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="KEITARO_", extra="ignore")

    url: str = "https://in.posdk.xyz"
    api_key: str = ""


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DATABASE_", extra="ignore")

    url: str = "sqlite+aiosqlite:///./adrobot.db"

    @field_validator("url")
    @classmethod
    def _async_driver(cls, url: str) -> str:
        for sync, async_ in _ASYNC_DRIVERS.items():
            if url.startswith(sync):
                return async_ + url.removeprefix(sync)
        return url


class CampaignSettings(BaseSettings):
    """Defaults for new campaigns."""

    # Empty values (e.g. `DEFAULT_GROUP_ID=` passed through by docker compose) mean "not set"
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DEFAULT_", extra="ignore", env_ignore_empty=True)

    group_id: int | None = None
    traffic_source_id: int | None = None
    domain_id: int | None = None

    # Where the first flow sends visitors from the selected countries
    geo_redirect_url: str = Field("https://google.com", validation_alias="GEO_REDIRECT_URL")
