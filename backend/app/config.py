"""
Configuration settings for Daisy Risk Engine backend
"""

from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings"""
    
    # Database
    database_url: str = Field(default="sqlite+aiosqlite:///./data/daisy.db", env="DATABASE_URL")
    
    # API Settings
    api_host: str = Field(default="0.0.0.0", env="API_HOST")
    api_port: int = Field(default=8000, env="API_PORT")
    
    # Data Fetching
    yfinance_timeout: int = Field(default=30, env="YFINANCE_TIMEOUT")
    cache_ttl_minutes: int = Field(default=60, env="CACHE_TTL_MINUTES")

    # Alpha Vantage fallback (free tier per key: 25 req/day, 5 req/min).
    # Provide ONE key via ALPHA_VANTAGE_API_KEY or several via
    # ALPHA_VANTAGE_API_KEYS="key1,key2,key3" (comma/semicolon/space separated);
    # they are rotated automatically when one hits a rate limit.
    alpha_vantage_api_key: Optional[str] = Field(default=None, env="ALPHA_VANTAGE_API_KEY")
    alpha_vantage_api_keys: str = Field(default="", env="ALPHA_VANTAGE_API_KEYS")
    alpha_vantage_daily_limit: int = Field(default=25, env="ALPHA_VANTAGE_DAILY_LIMIT")
    alpha_vantage_minute_limit: int = Field(default=5, env="ALPHA_VANTAGE_MINUTE_LIMIT")
    alpha_vantage_timeout: int = Field(default=30, env="ALPHA_VANTAGE_TIMEOUT")
    
    # Application
    debug: bool = Field(default=True, env="DEBUG")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    
    # CORS
    allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        env="ALLOWED_ORIGINS"
    )
    
    # Environment
    environment: str = Field(default="development", env="ENVIRONMENT")
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()