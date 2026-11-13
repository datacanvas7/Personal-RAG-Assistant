"""Application settings, loaded from environment variables.

Every tunable value and every secret enters the application here and nowhere else.
Secrets have no defaults: a missing secret stops the process at startup instead of
silently running with a guessable value.
"""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    # In containers the values come from real environment variables. The .env lookups
    # only matter when running outside Docker, from backend/ or from the repo root.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_name: str = "Personal RAG Assistant"
    version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_v1_prefix: str = "/api/v1"

    # Comma-separated browser origins allowed to call the API directly. Empty by
    # default because the browser normally reaches the API through the frontend's
    # same-origin proxy and needs no CORS at all.
    backend_cors_origins: str = ""

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "rag"
    postgres_user: str = "rag"
    postgres_password: SecretStr

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    @property
    def database_url(self) -> URL:
        """SQLAlchemy URL for psycopg 3 (the same driver serves sync and async engines).

        Built with ``URL.create`` rather than string formatting so that passwords
        containing ``@``, ``/`` or ``:`` are escaped correctly.
        """
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
