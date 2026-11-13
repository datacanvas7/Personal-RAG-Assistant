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
