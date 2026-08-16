from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPTION_PLATFORM_", env_file=".env")

    database_url: str = "postgresql+asyncpg://option:option@localhost:5432/option_platform"
    database_ssl: bool = False
    market_profile: str | None = None
    market_token: str | None = None
    stale_after_seconds: int = 30
    runtime_poll_seconds: float = 1.0
    live_trading_enabled: bool = False

    @model_validator(mode="after")
    def prohibit_live_trading(self) -> Settings:
        if self.live_trading_enabled:
            raise ValueError("live trading is outside v1 and cannot be enabled")
        return self


settings = Settings()
