import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.workers.tasks import ping


def test_database_url_escapes_special_characters_in_the_password() -> None:
    settings = Settings(postgres_password="p@ss/w:rd#1")

    rendered = settings.database_url.render_as_string(hide_password=False)

    assert rendered.startswith("postgresql+psycopg://rag:")
    # Exactly one unescaped "@" must remain: the one separating credentials from host.
    assert rendered.count("@") == 1
    assert settings.database_url.password == "p@ss/w:rd#1"


def test_password_is_not_exposed_by_repr() -> None:
    settings = Settings(postgres_password="super-secret")

    assert "super-secret" not in repr(settings)


def test_cors_origins_are_parsed_and_trimmed() -> None:
    settings = Settings(
        postgres_password="x",
        backend_cors_origins=" http://localhost:3000 ,https://example.com,, ",
    )

    assert settings.cors_origins == ["http://localhost:3000", "https://example.com"]


def test_cors_is_disabled_by_default() -> None:
    assert Settings(postgres_password="x").cors_origins == []


def test_ping_task_returns_pong() -> None:
    assert ping() == "pong"


def test_jwt_secret_must_be_long_enough() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(postgres_password="x", jwt_secret_key="too-short")


def test_secrets_are_not_exposed_by_repr() -> None:
    settings = Settings(postgres_password="x", jwt_secret_key="s" * 40)

    assert "s" * 40 not in repr(settings)


@pytest.mark.parametrize(
    "overrides",
    [
        {"cookie_secure": False},
        {"jwt_secret_key": "change-me-" + "x" * 30},
        {"postgres_password": "change-me"},
    ],
    ids=["insecure-cookie", "placeholder-jwt-secret", "placeholder-db-password"],
)
def test_production_refuses_unsafe_configuration(overrides: dict[str, object]) -> None:
    safe: dict[str, object] = {
        "environment": "production",
        "postgres_password": "a-real-password",
        "jwt_secret_key": "k" * 40,
        "cookie_secure": True,
    }

    Settings(**safe)  # type: ignore[arg-type]  # the safe baseline is accepted
    with pytest.raises(ValidationError):
        Settings(**(safe | overrides))  # type: ignore[arg-type]


def test_openai_embeddings_require_an_api_key() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(postgres_password="x", embedding_provider="openai", openai_api_key=None)


def test_embedding_model_defaults_depend_on_the_provider() -> None:
    local = Settings(postgres_password="x")
    hosted = Settings(postgres_password="x", embedding_provider="openai", openai_api_key="sk-test")

    assert local.resolved_embedding_model == "BAAI/bge-small-en-v1.5"
    assert hosted.resolved_embedding_model == "text-embedding-3-small"
    assert Settings(
        postgres_password="x", embedding_model="org/other"
    ).resolved_embedding_model == ("org/other")


def test_openai_key_is_not_exposed_by_repr() -> None:
    settings = Settings(
        postgres_password="x", embedding_provider="openai", openai_api_key="sk-very-secret"
    )

    assert "sk-very-secret" not in repr(settings)


def test_rate_limit_settings_must_be_well_formed() -> None:
    with pytest.raises(ValidationError, match="RATE_LIMIT_LOGIN_IP"):
        Settings(postgres_password="x", rate_limit_login_ip="ten per minute")


def test_api_docs_are_on_outside_production_and_off_in_production() -> None:
    assert Settings(postgres_password="x", environment="development").api_docs_enabled
    production = Settings(
        postgres_password="a-real-looking-password",
        jwt_secret_key="a-real-looking-secret-that-is-long-enough-0123456789",
        environment="production",
        cookie_secure=True,
    )
    assert not production.api_docs_enabled


def test_api_docs_can_be_forced_on_in_production() -> None:
    production = Settings(
        postgres_password="a-real-looking-password",
        jwt_secret_key="a-real-looking-secret-that-is-long-enough-0123456789",
        environment="production",
        cookie_secure=True,
        enable_api_docs=True,
    )
    assert production.api_docs_enabled


def test_database_pool_settings_have_safe_defaults() -> None:
    settings = Settings(postgres_password="x")

    assert (settings.db_pool_size, settings.db_max_overflow) == (10, 10)
    assert settings.db_statement_timeout_ms == 30_000
    with pytest.raises(ValidationError):
        Settings(postgres_password="x", db_statement_timeout_ms=0)
