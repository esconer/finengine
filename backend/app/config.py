"""
Configuration settings for Daisy Risk Engine backend

Env binding: pydantic-settings matches environment variables to field names
uppercased (DATABASE_URL -> database_url, DEBUG -> debug, ...). Do not add
`env=` kwargs to Field — on pydantic v2 they are silently ignored (they land
in json_schema_extra, they do NOT bind), which made renames silently drop
their env override.
"""

import json
from typing import Annotated, Optional
from pydantic_settings import BaseSettings, NoDecode
from pydantic import Field, field_validator
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    """Application settings"""
    
    # Database
    database_url: str = Field(default="sqlite+aiosqlite:///./data/daisy.db")

    @field_validator("database_url")
    @classmethod
    def database_url_must_be_async_sqlite(cls, value: str) -> str:
        """Reject the sync URL that create_async_engine cannot load.

        SQLite is the only database driver installed by this project.  Keeping
        the check at Settings construction makes Compose/operator mistakes fail
        before any table or user file is touched.
        """

        try:
            url = make_url(value)
        except Exception as exc:  # pydantic reports a normal validation error
            raise ValueError(f"invalid DATABASE_URL: {exc}") from exc
        if url.get_backend_name() == "sqlite" and url.get_driver_name() != "aiosqlite":
            raise ValueError(
                "SQLite DATABASE_URL must use sqlite+aiosqlite for the async engine"
            )
        return value
    
    # API Settings
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000)
    
    # Data Fetching
    yfinance_timeout: int = Field(default=30)
    cache_ttl_minutes: int = Field(default=60)

    # Analytics
    risk_free_rate: float = Field(default=0.02)  # 2% annual risk-free rate

    # Alpha Vantage fallback (free tier per key: 25 req/day, 5 req/min).
    # Provide ONE key via ALPHA_VANTAGE_API_KEY or several via
    # ALPHA_VANTAGE_API_KEYS="key1,key2,key3" (comma/semicolon/space separated);
    # they are rotated automatically when one hits a rate limit.
    alpha_vantage_api_key: Optional[str] = Field(default=None)
    alpha_vantage_api_keys: str = Field(default="")
    alpha_vantage_daily_limit: int = Field(default=25)
    alpha_vantage_minute_limit: int = Field(default=5)
    alpha_vantage_timeout: int = Field(default=30)
    
    # Application (SQL echo additionally requires environment == "development",
    # see app/db/database.py — debug alone must not spam stdout with queries)
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    
    # CORS: NoDecode skips pydantic-settings' strict JSON decoding of env vars,
    # so the value may be a JSON array OR the natural comma-separated string.
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ],
    )

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                return json.loads(v)
            return [part.strip() for part in v.split(",") if part.strip()]
        return v
    
    # Environment
    environment: str = Field(default="development")
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()
