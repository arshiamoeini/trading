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
    tsetmc_base_url: str = "https://cdn.tsetmc.com"
    tsetmc_markets: str = "TSE,IFB"
    tsetmc_poll_seconds: float = 5.0
    tsetmc_timeout_seconds: float = 10.0
    tsetmc_max_retries: int = 3
    tsetmc_depth_watchlist: str = ""
    tsetmc_depth_concurrency: int = 4
    tsetmc_timezone: str = "Asia/Tehran"

    @model_validator(mode="after")
    def prohibit_live_trading(self) -> Settings:
        if self.live_trading_enabled:
            raise ValueError("live trading is outside v1 and cannot be enabled")
        return self


settings = Settings()
