from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration from environment / `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Use mysql+aiomysql://user:pass@host:3306/dbname for async SQLAlchemy
    DATABASE_URL: str = Field(
        default="mysql+aiomysql://user:password@127.0.0.1:3306/app",
        description="SQLAlchemy async URL (aiomysql driver).",
    )
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    REDIS_DB: int = 0
    LOG_LEVEL: str = "INFO"
    ENV: str = "development"
    JWT_SECRET: str = Field(default="dev-only-change-in-production", min_length=1)
    JWT_ALGORITHM: str = "HS256"


settings = Settings()
