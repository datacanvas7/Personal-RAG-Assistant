"""Application settings, loaded from environment variables.

Every tunable value and every secret enters the application here and nowhere else.
Secrets have no defaults: a missing secret stops the process at startup instead of
silently running with a guessable value.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

# Values shipped in .env.example. They must never reach production.
_PLACEHOLDER_PREFIX = "change-me"
_MIN_JWT_SECRET_LENGTH = 32


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

    # --- Authentication ---------------------------------------------------------------
    # The signing algorithm is deliberately not configurable (HS256, fixed in
    # core/security.py): accepting the algorithm from configuration or from the token
    # header is the root of "alg confusion" attacks.
    jwt_secret_key: SecretStr
    access_token_expire_minutes: int = Field(default=15, ge=1)
    refresh_token_expire_days: int = Field(default=7, ge=1)
    # A refresh token that was rotated away within this many seconds is rejected
    # without revoking the session. Two browser tabs refreshing at the same moment is
    # normal; only a *later* replay is treated as theft.
    refresh_reuse_grace_seconds: int = Field(default=10, ge=0)
    # Send the refresh cookie only over HTTPS. Must be true in production.
    cookie_secure: bool = False

    # --- Embeddings -------------------------------------------------------------------
    # Fixed in the database column type; changing it needs a migration and a re-index.
    embedding_dimension: int = Field(default=384, ge=1, le=2000)

    # --- Documents --------------------------------------------------------------------
    # Where uploaded files live. In Docker this is a volume shared by the API and the
    # worker, because the API writes the file and the worker reads it.
    upload_dir: Path = Path("data/uploads")
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    # Limits that bound the work one hostile file can cause (see ingestion/loaders.py).
    max_pdf_pages: int = Field(default=1000, ge=1)
    max_extracted_chars: int = Field(default=5_000_000, ge=1)
    # A PDF page with fewer extracted characters than this counts as "image only"; if at
    # least half of the pages are image-only the document is rejected as needing OCR.
    ocr_min_chars_per_page: int = Field(default=20, ge=0)
    # Chunk size in characters, not tokens: this avoids shipping a tokenizer, and 1500
    # characters (about 350 English tokens) fits the 512-token window of small embedding
    # models with room to spare.
    chunk_size_chars: int = Field(default=1500, ge=200)
    chunk_overlap_chars: int = Field(default=200, ge=0)

    @model_validator(mode="after")
    def _check_chunking(self) -> Self:
        if self.chunk_overlap_chars * 2 > self.chunk_size_chars:
            raise ValueError("CHUNK_OVERLAP_CHARS must be at most half of CHUNK_SIZE_CHARS")
        return self

    @model_validator(mode="after")
    def _check_secrets(self) -> Self:
        jwt_secret = self.jwt_secret_key.get_secret_value()
        if len(jwt_secret) < _MIN_JWT_SECRET_LENGTH:
            raise ValueError(f"JWT_SECRET_KEY must be at least {_MIN_JWT_SECRET_LENGTH} characters")
        if self.environment == "production":
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
            for name, secret in (
                ("JWT_SECRET_KEY", jwt_secret),
                ("POSTGRES_PASSWORD", self.postgres_password.get_secret_value()),
            ):
                if secret.startswith(_PLACEHOLDER_PREFIX):
                    raise ValueError(f"{name} still has the .env.example placeholder value")
        return self

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
